"""Incrementele sync: haal alleen nieuwe/gewijzigde orders op uit Exact Online.

Draait elke 15 minuten via GitHub Actions en:
1. Haalt orders op die gewijzigd zijn sinds de laatste sync
2. Hercontroleert alle openstaande orders op statuswijzigingen
3. Upsert alles naar Supabase

State (last sync timestamp) wordt opgeslagen in Supabase config tabel,
met fallback naar lokaal bestand voor ontwikkeling.
"""

import os
import sys
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from supabase import create_client

from exact_client import ExactClient
from sync_orders import (
    ORDER_FIELDS,
    LINE_FIELDS,
    transform_order,
    transform_order_line,
    parse_odata_date,
)

load_dotenv()
log = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
STATE_FILE = "sync_state.json"
SYNC_STATE_KEY = "last_sync"


def _get_sb():
    if SUPABASE_URL and SUPABASE_KEY:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    return None


def load_last_sync():
    """Lees het tijdstip van de laatste succesvolle sync (Supabase of lokaal)."""
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
    """Sla het tijdstip van de huidige sync op (Supabase + lokaal)."""
    sb = _get_sb()
    if sb:
        try:
            sb.table("config").upsert({
                "key": SYNC_STATE_KEY,
                "value": timestamp,
                "updated_at": "now()",
            }, on_conflict="key").execute()
        except Exception:
            pass
    with open(STATE_FILE, "w") as f:
        json.dump({"last_sync": timestamp}, f, indent=2)


def fetch_modified_orders(exact, since):
    """Haal orders op die gewijzigd zijn sinds het opgegeven tijdstip."""
    since = since.strip('"')
    orders = exact.get("/salesorder/SalesOrders", params={
        "$filter": f"Modified ge datetime'{since}'",
        "$select": f"{ORDER_FIELDS},Modified",
        "$orderby": "Modified desc",
    })
    return orders


def fetch_open_orders(exact):
    """Haal alle orders op die nog niet volledig afgerond zijn.

    Dit vangt statuswijzigingen op die we anders zouden missen,
    bijv. een levering die van 'Open' naar 'Volledig' gaat.
    """
    orders = exact.get("/salesorder/SalesOrders", params={
        "$filter": "DeliveryStatus ne 21 or InvoiceStatus ne 2",
        "$select": f"{ORDER_FIELDS},Modified",
        "$orderby": "OrderDate desc",
    })
    return orders


def upsert_orders(sb, exact, orders):
    """Upsert orders + orderregels naar Supabase. Retourneert counts."""
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

        lines = exact.get("/salesorder/SalesOrderLines", params={
            "$filter": f"OrderNumber eq {order['OrderNumber']}",
            "$select": LINE_FIELDS,
        })

        for line in lines:
            line_data = transform_order_line(line, order_id)
            sb.table("order_lines").upsert(
                line_data, on_conflict="exact_line_id"
            ).execute()

        synced_lines += len(lines)
        time.sleep(0.3)

    return synced_orders, synced_lines


def sync_incremental(exact=None, dry_run=False):
    """Voer een incrementele sync uit.

    - Eerste keer: haalt alle orders op van 2026
    - Daarna: alleen gewijzigde orders + alle openstaande orders
    """
    if exact is None:
        exact = ExactClient()

    last_sync = load_last_sync()
    sync_start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    if last_sync is None:
        log.info("Eerste sync — alle 2026 orders ophalen...")
        all_orders = exact.get("/salesorder/SalesOrders", params={
            "$filter": "OrderDate ge datetime'2026-01-01'",
            "$select": f"{ORDER_FIELDS},Modified",
            "$orderby": "OrderDate desc",
        })
        log.info(f"{len(all_orders)} orders gevonden (initiële sync)")
    else:
        log.info(f"Incrementele sync sinds {last_sync}")

        modified = fetch_modified_orders(exact, last_sync)
        log.info(f"{len(modified)} gewijzigde orders sinds laatste sync")

        open_orders = fetch_open_orders(exact)
        log.info(f"{len(open_orders)} openstaande orders hercontroleerd")

        # Combineer en deduplicate op OrderID
        seen = {}
        for o in modified + open_orders:
            seen[o["OrderID"]] = o
        all_orders = list(seen.values())
        log.info(f"{len(all_orders)} unieke orders te syncen")

    if dry_run:
        for o in all_orders[:15]:
            status = o.get("DeliveryStatusDescription", "?")
            log.info(f"  #{o['OrderNumber']} {o.get('OrderedByName', '?')} "
                     f"[{status}] — {o.get('Modified', '?')}")
        if len(all_orders) > 15:
            log.info(f"  ... en {len(all_orders) - 15} meer")
        return {"orders": len(all_orders), "lines": 0, "dry_run": True}

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    synced_orders, synced_lines = upsert_orders(sb, exact, all_orders)

    save_last_sync(sync_start)
    log.info(f"Sync compleet: {synced_orders} orders, {synced_lines} regels bijgewerkt")

    return {"orders": synced_orders, "lines": synced_lines, "dry_run": False}


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler("sync_incremental.log"),
            logging.StreamHandler(),
        ],
    )
    dry_run = "--dry-run" in sys.argv
    result = sync_incremental(dry_run=dry_run)
    log.info(f"Resultaat: {result}")
