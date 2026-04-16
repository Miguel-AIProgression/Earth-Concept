"""Synchroniseer alle 2026 orders van Exact Online naar Supabase."""

import os
import logging
import time
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client
from exact_client import ExactClient
from edi_exclusions import is_edi_customer

load_dotenv()
log = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

ORDER_FIELDS = (
    "OrderID,OrderNumber,OrderDate,DeliveryStatus,DeliveryStatusDescription,"
    "InvoiceStatus,InvoiceStatusDescription,CreatorFullName,OrderedByName,"
    "Description,YourRef,DeliveryDate,AmountDC"
)

LINE_FIELDS = (
    "ID,OrderID,OrderNumber,ItemCode,ItemDescription,"
    "Quantity,QuantityDelivered,NetPrice,AmountDC,DeliveryDate"
)


def parse_odata_date(date_str):
    """Parse Exact Online OData date format '/Date(1234567890000)/'."""
    if not date_str:
        return None
    try:
        ms = int(date_str.replace("/Date(", "").replace(")/", ""))
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        return None


def transform_order(raw):
    return {
        "exact_order_id": raw["OrderID"],
        "order_number": raw["OrderNumber"],
        "order_date": parse_odata_date(raw.get("OrderDate")),
        "delivery_status": raw.get("DeliveryStatus"),
        "delivery_status_description": raw.get("DeliveryStatusDescription"),
        "invoice_status": raw.get("InvoiceStatus"),
        "invoice_status_description": raw.get("InvoiceStatusDescription"),
        "creator": raw.get("CreatorFullName"),
        "customer_name": raw.get("OrderedByName"),
        "description": raw.get("Description"),
        "your_ref": raw.get("YourRef"),
        "delivery_date": parse_odata_date(raw.get("DeliveryDate")),
        "amount": raw.get("AmountDC"),
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }


def transform_order_line(raw, order_id):
    return {
        "order_id": order_id,
        "exact_line_id": raw["ID"],
        "item_code": raw.get("ItemCode"),
        "item_description": raw.get("ItemDescription"),
        "quantity": raw.get("Quantity"),
        "quantity_delivered": raw.get("QuantityDelivered"),
        "unit_price": raw.get("NetPrice"),
        "amount": raw.get("AmountDC"),
        "delivery_date": parse_odata_date(raw.get("DeliveryDate")),
    }


def sync_all(exact=None, dry_run=False):
    """Haal alle 2026 orders op en sync naar Supabase."""
    if exact is None:
        exact = ExactClient()

    log.info("Orders ophalen uit Exact Online (2026)...")
    orders = exact.get("/salesorder/SalesOrders", params={
        "$filter": "OrderDate ge datetime'2026-01-01'",
        "$select": ORDER_FIELDS,
        "$orderby": "OrderDate desc",
    })
    log.info(f"{len(orders)} orders gevonden")

    before = len(orders)
    orders = [o for o in orders if not is_edi_customer(o.get("OrderedByName"))]
    skipped = before - len(orders)
    if skipped:
        log.info(f"{skipped} EDI-orders overgeslagen, {len(orders)} te verwerken")

    if dry_run:
        for o in orders[:10]:
            log.info(f"  #{o['OrderNumber']} - {o.get('OrderedByName')} "
                     f"({o.get('CreatorFullName')}) - {o.get('DeliveryStatusDescription')}")
        if len(orders) > 10:
            log.info(f"  ... en {len(orders) - 10} meer")
        return orders

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    total_lines = 0

    for i, order in enumerate(orders):
        transformed = transform_order(order)
        result = sb.table("orders").upsert(
            transformed, on_conflict="exact_order_id"
        ).execute()
        db_order = result.data[0]
        order_id = db_order["id"]

        # Orderregels per order ophalen
        lines = exact.get("/salesorder/SalesOrderLines", params={
            "$filter": f"OrderNumber eq {order['OrderNumber']}",
            "$select": LINE_FIELDS,
        })

        for line in lines:
            line_data = transform_order_line(line, order_id)
            sb.table("order_lines").upsert(
                line_data, on_conflict="exact_line_id"
            ).execute()

        total_lines += len(lines)
        if (i + 1) % 25 == 0 or i == len(orders) - 1:
            log.info(f"  Voortgang: {i + 1}/{len(orders)} orders, {total_lines} regels")
        time.sleep(0.3)  # Voorkom rate limiting

    log.info(f"Sync compleet: {len(orders)} orders, {total_lines} regels")
    return orders


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    dry_run = "--dry-run" in sys.argv
    sync_all(dry_run=dry_run)
