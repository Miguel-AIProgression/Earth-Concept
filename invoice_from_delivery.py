"""Invoice-from-delivery matcher.

Leest dagelijks leverancier-Excel (Delta Wines) en matcht geleverde regels
tegen bestaande Exact-orders. Bouwt offline invoice-payloads; doet GEEN live
POST naar Exact. Orders met shortage komen op status 'review' in Supabase
`invoice_holds`; perfecte matches op 'ready_to_invoice'.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


# Mapping Excel-kolomnaam -> genormaliseerde snake_case key.
_COLUMN_MAP = {
    "Ordernummer": "order_number",
    "Factuurnummer": "invoice_number",
    "Orderdatum": "order_date",
    "Omschrijving: Kopregel": "header_description",
    "Uw ref.": "your_ref",
    "Dagboek: Code": "journal_code",
    "Betalingsconditie: Code": "payment_condition",
    "Opmerkingen": "remarks",
    "Code": "customer_code",
    "Naam": "customer_name",
    "Code (2)": "delivery_code",
    "Naam (2)": "delivery_name",
    "Artikelcode": "item_code",
    "Omschrijving": "description",
    "Aantal": "quantity_delivered",
    "Prijs per eenheid": "unit_price",
    "Nettoprijs": "net_price",
    "Kortingspercentage": "discount_pct",
    "BTW-code": "vat_code",
    "Opmerkingen (2)": "line_remarks",
    "Eenheid: Code": "unit",
    "Eenheid: Omschrijving": "unit_description",
}


def _clean(value: Any) -> Any:
    """Converteer NaN/NaT naar None; Timestamps naar ISO-string."""
    if value is None:
        return None
    # pandas NaT / NaN detectie
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def load_delivery_excel(path: str | Path, sheet: str = "import") -> list[dict]:
    """Lees 3e tabblad (default 'import') van leverancier-Excel.

    Returns lijst van dicts met genormaliseerde keys. Lege rijen (geen
    order_number en geen item_code) worden geskipt.
    """
    df = pd.read_excel(path, sheet_name=sheet)
    rows: list[dict] = []
    for _, raw in df.iterrows():
        mapped: dict[str, Any] = {}
        for col, key in _COLUMN_MAP.items():
            if col in df.columns:
                mapped[key] = _clean(raw[col])
            else:
                mapped[key] = None
        if not mapped.get("order_number") and not mapped.get("item_code"):
            continue
        rows.append(mapped)
    return rows


def _order_lookup(exact_orders: list[dict]) -> dict[str, dict]:
    return {str(o["OrderNumber"]): o for o in exact_orders}


def match_deliveries_to_orders(
    delivery_rows: list[dict],
    exact_orders: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Matcht delivery-regels tegen bestaande Exact-orders."""
    orders_by_num = _order_lookup(exact_orders)
    matches_by_order: dict[str, dict] = {}
    discrepancies: list[dict] = []

    for row in delivery_rows:
        order_number = row.get("order_number")
        item_code = row.get("item_code")
        delivered = row.get("quantity_delivered") or 0
        try:
            delivered = float(delivered)
        except (TypeError, ValueError):
            delivered = 0.0

        if not order_number:
            continue
        order_number = str(order_number)

        exact_order = orders_by_num.get(order_number)
        if exact_order is None:
            discrepancies.append(
                {
                    "type": "no_matching_order",
                    "order_number": order_number,
                    "item_code": item_code,
                    "reason": f"Order {order_number} bestaat niet in Exact",
                }
            )
            continue

        # Zoek regel op ItemCode
        exact_line = next(
            (l for l in exact_order["lines"] if l.get("ItemCode") == item_code),
            None,
        )
        if exact_line is None:
            discrepancies.append(
                {
                    "type": "no_matching_line",
                    "order_number": order_number,
                    "item_code": item_code,
                    "reason": f"Artikel {item_code} staat niet op order {order_number}",
                }
            )
            continue

        ordered = float(exact_line.get("Quantity") or 0)

        if delivered > ordered:
            discrepancies.append(
                {
                    "type": "excess_delivery",
                    "order_number": order_number,
                    "item_code": item_code,
                    "reason": (
                        f"Geleverd {delivered} > besteld {ordered} voor {item_code}"
                    ),
                }
            )
            continue

        shortage = ordered - delivered
        unit_price = exact_line.get("UnitPrice") or row.get("unit_price") or 0.0

        match = matches_by_order.setdefault(
            order_number,
            {
                "order_number": order_number,
                "order_id": exact_order.get("OrderID")
                or exact_order.get("OrderId")
                or exact_order.get("Id"),
                "your_ref": row.get("your_ref"),
                "customer_code": row.get("customer_code"),
                "customer_name": row.get("customer_name"),
                "lines": [],
                "has_shortage": False,
                "total_net": 0.0,
            },
        )
        line_entry = {
            "item_code": item_code,
            "item_id": exact_line.get("ItemId") or exact_line.get("Item"),
            "ordered": ordered,
            "delivered": delivered,
            "unit_price": float(unit_price),
            "description": row.get("description") or exact_line.get("Description"),
            "line_id": exact_line.get("Id"),
            "shortage": shortage,
        }
        match["lines"].append(line_entry)
        if shortage > 0:
            match["has_shortage"] = True
        match["total_net"] += delivered * float(unit_price)

    return list(matches_by_order.values()), discrepancies


def build_invoice_payload(match: dict, account_id: str) -> dict:
    """Bouw JSON-body voor POST /salesinvoice/SalesInvoices.

    Lijnen met delivered=0 worden geskipt. Doet zelf GEEN POST.
    """
    invoice_lines = []
    for line in match.get("lines", []):
        if not line.get("delivered"):
            continue
        invoice_lines.append(
            {
                "Item": line.get("item_id"),
                "Quantity": line["delivered"],
                "UnitPrice": line.get("unit_price", 0.0),
                "Description": line.get("description"),
            }
        )
    return {
        "InvoiceTo": account_id,
        "OrderedBy": account_id,
        "YourRef": match.get("your_ref") or match.get("order_number"),
        "SalesInvoiceLines": invoice_lines,
    }


def process_delivery_file(
    excel_path: str | Path,
    exact_orders: list[dict],
    sb=None,
) -> dict:
    """Orchestrator: load + match + schrijf holds naar Supabase. Geen Exact POST."""
    rows = load_delivery_excel(excel_path)
    matches, discrepancies = match_deliveries_to_orders(rows, exact_orders)

    shortages = 0
    ready = 0
    for m in matches:
        if m["has_shortage"]:
            shortages += 1
            status = "review"
        else:
            ready += 1
            status = "ready_to_invoice"

        if sb is not None:
            # groepeer discrepancies per order (alleen meegeven die dit order-number betreffen)
            order_discs = [
                d for d in discrepancies if d.get("order_number") == m["order_number"]
            ]
            sb.table("invoice_holds").upsert(
                {
                    "order_number": m["order_number"],
                    "order_id": m.get("order_id"),
                    "status": status,
                    "match_data": m,
                    "discrepancies": order_discs,
                },
                on_conflict="order_number",
            ).execute()

    return {
        "matched": len(matches),
        "shortages": shortages,
        "discrepancies": len(discrepancies),
        "ready": ready,
    }
