"""Incremental sync for Exact Online orders.

Runs every 15 minutes and:
1. Fetches orders modified since the last successful sync
2. Rechecks orders that are not in a final delivery/invoice state
3. Upserts changes into Supabase

The last sync timestamp is stored in Supabase config, with a local file
fallback for local development.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from supabase import create_client

from edi_exclusions import is_edi_customer
from exact_client import ExactClient
from sync_orders import LINE_FIELDS, ORDER_FIELDS, transform_order, transform_order_line

load_dotenv()
log = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
STATE_FILE = "sync_state.json"
SYNC_STATE_KEY = "last_sync"
FINAL_STATUS_CODES = (21, 45)
FINAL_STATUS_FILTER = (
    f"delivery_status.not.in.({FINAL_STATUS_CODES[0]},{FINAL_STATUS_CODES[1]}),"
    f"invoice_status.not.in.({FINAL_STATUS_CODES[0]},{FINAL_STATUS_CODES[1]})"
)


def _get_sb():
    if SUPABASE_URL and SUPABASE_KEY:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    return None


def load_last_sync():
    """Read the last successful sync timestamp."""
    sb = _get_sb()
    if sb:
        try:
            result = sb.table("config").select("value").eq("key", SYNC_STATE_KEY).execute()
            if result.data:
                return result.data[0]["value"]
        except Exception:
            pass

    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            state = json.load(f)
            return state.get("last_sync")

    return None


def save_last_sync(timestamp):
    """Persist the current sync timestamp."""
    sb = _get_sb()
    if sb:
        try:
            sb.table("config").upsert(
                {
                    "key": SYNC_STATE_KEY,
                    "value": timestamp,
                    "updated_at": "now()",
                },
                on_conflict="key",
            ).execute()
        except Exception:
            pass

    with open(STATE_FILE, "w") as f:
        json.dump({"last_sync": timestamp}, f, indent=2)


def fetch_modified_orders(exact, since):
    """Fetch orders modified since the given timestamp."""
    since = since.strip('"')
    return exact.get(
        "/salesorder/SalesOrders",
        params={
            "$filter": f"Modified ge datetime'{since}'",
            "$select": f"{ORDER_FIELDS},Modified",
            "$orderby": "Modified desc",
        },
    )


def fetch_open_orders(exact, sb):
    """Recheck only orders that are not in a final state yet."""
    if sb is None:
        return []

    result = (
        sb.table("orders")
        .select("exact_order_id, order_number")
        .or_(FINAL_STATUS_FILTER)
        .execute()
    )
    if not result.data:
        return []

    orders = []
    for row in result.data:
        try:
            batch = exact.get(
                "/salesorder/SalesOrders",
                params={
                    "$filter": f"OrderID eq guid'{row['exact_order_id']}'",
                    "$select": f"{ORDER_FIELDS},Modified",
                },
            )
            orders.extend(batch)
        except Exception as exc:
            log.warning(f"Kon order #{row['order_number']} niet ophalen: {exc}")

    return orders


def upsert_orders(sb, exact, orders):
    """Upsert orders and order lines into Supabase."""
    synced_orders = 0
    synced_lines = 0

    for order in orders:
        transformed = transform_order(order)
        result = sb.table("orders").upsert(
            transformed, on_conflict="exact_order_id"
        ).execute()
        db_order = result.data[0]
        order_id = db_order["id"]
        synced_orders += 1

        lines = exact.get(
            "/salesorder/SalesOrderLines",
            params={
                "$filter": f"OrderNumber eq {order['OrderNumber']}",
                "$select": LINE_FIELDS,
            },
        )

        for line in lines:
            line_data = transform_order_line(line, order_id)
            sb.table("order_lines").upsert(
                line_data, on_conflict="exact_line_id"
            ).execute()

        synced_lines += len(lines)
        time.sleep(0.3)

    return synced_orders, synced_lines


def sync_incremental(exact=None, dry_run=False):
    """Run an incremental sync.

    - First run: fetch all 2026 orders
    - Subsequent runs: fetch modified orders plus not-yet-final orders
    """
    if exact is None:
        exact = ExactClient()

    last_sync = load_last_sync()
    sync_start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    if last_sync is None:
        log.info("Eerste sync - alle 2026 orders ophalen...")
        all_orders = exact.get(
            "/salesorder/SalesOrders",
            params={
                "$filter": "OrderDate ge datetime'2026-01-01'",
                "$select": f"{ORDER_FIELDS},Modified",
                "$orderby": "OrderDate desc",
            },
        )
        log.info(f"{len(all_orders)} orders gevonden (initiele sync)")
    else:
        log.info(f"Incrementele sync sinds {last_sync}")

        modified = fetch_modified_orders(exact, last_sync)
        log.info(f"{len(modified)} gewijzigde orders sinds laatste sync")

        sb = create_client(SUPABASE_URL, SUPABASE_KEY)
        open_orders = fetch_open_orders(exact, sb)
        log.info(f"{len(open_orders)} openstaande orders hercontroleerd")

        seen = {}
        for order in modified + open_orders:
            seen[order["OrderID"]] = order
        all_orders = list(seen.values())
        log.info(f"{len(all_orders)} unieke orders te syncen")

    before = len(all_orders)
    all_orders = [o for o in all_orders if not is_edi_customer(o.get("OrderedByName"))]
    skipped = before - len(all_orders)
    if skipped:
        log.info(f"{skipped} EDI-orders overgeslagen, {len(all_orders)} over")

    if dry_run:
        for order in all_orders[:15]:
            status = order.get("DeliveryStatusDescription", "?")
            customer = order.get("OrderedByName", "?")
            modified = order.get("Modified", "?")
            log.info(f"  #{order['OrderNumber']} {customer} [{status}] - {modified}")
        if len(all_orders) > 15:
            log.info(f"  ... en {len(all_orders) - 15} meer")
        return {"orders": len(all_orders), "lines": 0, "dry_run": True}

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    synced_orders, synced_lines = upsert_orders(sb, exact, all_orders)

    save_last_sync(sync_start)
    log.info(f"Sync compleet: {synced_orders} orders, {synced_lines} regels bijgewerkt")

    return {"orders": synced_orders, "lines": synced_lines, "dry_run": False}


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler("sync_incremental.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    dry_run = "--dry-run" in sys.argv
    result = sync_incremental(dry_run=dry_run)
    log.info(f"Resultaat: {result}")
