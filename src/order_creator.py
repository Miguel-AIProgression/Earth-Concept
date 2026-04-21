"""Bouw een SalesOrder-payload voor Exact Online, incl. klant- en artikelmatching.

Matching gebeurt tegen een lokale Supabase-katalogus (nightly gesynced door
catalog_sync.py) met rapidfuzz en alias-leren — zie src/matcher.py.
Deze module doet GEEN live POST naar Exact; dat gebeurt in process_pipeline.

Mogelijke parse_status waarden in incoming_orders:
    pending | parsed | needs_review | ready_for_approval | approved | created | failed
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import matcher

log = logging.getLogger(__name__)


def _date_to_odata(date_str: str) -> str:
    """YYYY-MM-DD -> ISO 8601 datetime-string zoals Exact accepteert in POSTs."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.strftime("%Y-%m-%dT00:00:00")


def build_salesorder_payload(
    parsed: dict,
    account_id: str,
    matched_items: list[dict],
    description: str | None = None,
) -> dict:
    """Bouw JSON-body voor POST /salesorder/SalesOrders."""
    lines_payload = []
    for m in matched_items:
        if not m.get("item_id"):
            raise ValueError(
                f"Kan geen payload bouwen: item_id ontbreekt voor regel {m.get('line')}"
            )
        line = m["line"]
        line_payload: dict[str, Any] = {
            "Item": m["item_id"],
            "Quantity": line.get("quantity", 0),
            "Description": line.get("description", ""),
        }
        # UnitPrice alleen meesturen als de PDF een echte prijs bevat;
        # anders laat Exact de standaardprijs van het Item / de prijslijst
        # van de klant toepassen (nul-prijzen zijn geen geldige waarde).
        unit_price = line.get("unit_price")
        if isinstance(unit_price, (int, float)) and unit_price > 0:
            line_payload["UnitPrice"] = unit_price
        lines_payload.append(line_payload)

    # Description valt terug op de inkooporder/PO-nummer: dat is de herkenning
    # die Patrick in Exact nodig heeft -- YourRef is niet altijd zichtbaar in
    # overzichten, Description wel.
    customer_ref = parsed.get("customer_reference") or ""
    payload: dict[str, Any] = {
        "OrderedBy": account_id,
        "YourRef": customer_ref,
        "Description": description or parsed.get("description") or customer_ref,
        "SalesOrderLines": lines_payload,
    }

    delivery_date = parsed.get("delivery_date")
    if delivery_date:
        payload["DeliveryDate"] = _date_to_odata(delivery_date)

    return payload


def compute_overall_confidence(
    customer_match: dict | None, item_matches: list[dict]
) -> float:
    """Gewogen gemiddelde: customer 40%, items 60%.

    0.0 als customer ontbreekt of als een item_id None is.
    """
    if not customer_match:
        return 0.0
    if not item_matches:
        return 0.0
    if any(m.get("item_id") is None for m in item_matches):
        return 0.0

    cust_conf = float(customer_match.get("confidence", 0.0))
    item_conf = sum(float(m.get("confidence", 0.0)) for m in item_matches) / len(item_matches)
    return cust_conf * 0.4 + item_conf * 0.6


def prepare_order_for_review(incoming_row: dict, client, sb) -> dict:
    """Match klant + items via Supabase-katalogus, bouw payload, persist.

    ``client`` (ExactClient) is alleen nog nodig voor de uiteindelijke POST.
    """
    parsed = dict(incoming_row.get("parsed_data") or {})
    customer_name = parsed.get("customer_name") or parsed.get("customer") or ""
    lines = parsed.get("lines") or []

    customer_match = matcher.match_customer(sb, customer_name)
    # Fallback: geen naam-hit? Probeer op postcode/stad/straat van het
    # afleveradres. Blijft 'address'-source (nooit auto-gate) zodat
    # Patrick altijd bevestigt.
    if customer_match is None and client is not None:
        customer_match = matcher.match_customer_by_address(
            client, sb, parsed.get("delivery_address"), customer_name_hint=customer_name
        )
    item_matches = matcher.match_items(sb, lines)
    confidence = compute_overall_confidence(customer_match, item_matches)

    payload = None
    build_error = None
    if customer_match and all(m.get("item_id") for m in item_matches) and item_matches:
        try:
            payload = build_salesorder_payload(
                parsed,
                customer_match["id"],
                item_matches,
                description=parsed.get("description"),
            )
        except ValueError as e:
            build_error = str(e)
            log.warning("Payload build mislukt: %s", e)

    parsed["matched_customer"] = customer_match
    parsed["matched_items"] = item_matches
    parsed["salesorder_payload"] = payload
    parsed["match_confidence"] = confidence
    if build_error:
        parsed["match_error"] = build_error

    # Fuzzy item-matches zijn te riskant voor auto-gate: zelfs bij hoge
    # WRatio-score kan het product compleet verkeerd zijn (bv. Sparkling
    # vs. ANWB-TT). Vereis dat elk item via code of alias is gekoppeld.
    trusted_item_sources = {"code", "code-prefix", "alias"}
    all_items_trusted = bool(item_matches) and all(
        (m.get("source") in trusted_item_sources) for m in item_matches
    )

    # Zelfde eis voor de klant: een fuzzy WRatio van 0.85+ is niet betrouwbaar
    # genoeg om blind te POSTen. "Inbev Nederland NV" matchte bv. op
    # "Independent Films Nederland B.V." (0.855). Alleen exacte naam of een
    # eerder bevestigde alias mag auto-gate passeren.
    trusted_customer_sources = {"alias", "exact", "manual"}
    customer_trusted = bool(customer_match) and (
        customer_match.get("source") in trusted_customer_sources
    )

    # Elke regel moet een echte prijs hebben; zonder prijs valt Exact
    # terug op de standaard-prijslijst en dat willen we niet blind doen.
    all_lines_priced = bool(item_matches) and all(
        isinstance((m.get("line") or {}).get("unit_price"), (int, float))
        and (m.get("line") or {}).get("unit_price", 0) > 0
        for m in item_matches
    )

    # Auto-approve boven 0.85 met vertrouwde match (klant én items) + prijs
    # op elke regel: pipeline POST direct naar Exact. Fuzzy klant- of item-
    # match of ontbrekende prijs -> needs_review.
    if (
        payload is not None
        and confidence >= 0.85
        and customer_trusted
        and all_items_trusted
        and all_lines_priced
    ):
        new_status = "approved"
    else:
        new_status = "needs_review"

    update = {
        "parsed_data": parsed,
        "parse_status": new_status,
    }

    try:
        sb.table("incoming_orders").update(update).eq("id", incoming_row["id"]).execute()
    except Exception as e:
        log.error("Kon incoming_orders rij niet updaten: %s", e)

    updated_row = dict(incoming_row)
    updated_row.update(update)
    return updated_row
