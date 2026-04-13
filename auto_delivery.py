"""Automatisch GoodsDeliveries aanmaken voor open orders (excl. EDI-klanten)."""

import sys
import logging

from edi_exclusions import is_edi_customer
from exact_client import ExactClient

log = logging.getLogger(__name__)


def get_open_non_edi_orders(client):
    """Haal alle open orders op, behalve orders voor EDI-klanten."""
    orders = client.get("/salesorder/SalesOrders", params={
        "$filter": "DeliveryStatus eq 12",
        "$select": "OrderID,OrderNumber,OrderDate,DeliveryStatus,"
                   "CreatorFullName,OrderedByName,Description,YourRef,DeliveryDate",
        "$orderby": "OrderDate desc",
    })
    return [o for o in orders
            if o.get("DeliveryStatus") == 12
            and not is_edi_customer(o.get("OrderedByName"))]


def get_undelivered_lines(client, order_id):
    """Haal orderregels op die nog niet (volledig) afgeleverd zijn."""
    lines = client.get("/salesorder/SalesOrderLines", params={
        "$filter": f"OrderID eq guid'{order_id}'",
        "$select": "ID,OrderID,OrderNumber,ItemCode,ItemDescription,"
                   "Quantity,QuantityDelivered,DeliveryDate",
    })
    return [l for l in lines if l.get("Quantity", 0) > l.get("QuantityDelivered", 0)]


def create_goods_delivery(client, order, lines):
    """Maak een GoodsDelivery aan voor een order met de gegeven regels."""
    if not lines:
        raise ValueError(f"Geen regels voor order #{order.get('OrderNumber')}")

    delivery_lines = []
    for line in lines:
        remaining = line["Quantity"] - line.get("QuantityDelivered", 0)
        delivery_lines.append({
            "SalesOrderLineID": line["ID"],
            "QuantityDelivered": remaining,
        })

    payload = {
        "Description": order.get("Description", ""),
        "DeliveryDate": order.get("DeliveryDate"),
        "GoodsDeliveryLines": delivery_lines,
    }

    return client.post("/salesorder/GoodsDeliveries", payload)


def process_open_orders(client, dry_run=False):
    """Verwerk alle open niet-EDI orders: maak GoodsDeliveries aan."""
    orders = get_open_non_edi_orders(client)
    log.info(f"{len(orders)} open niet-EDI orders gevonden")

    if dry_run:
        log.info("DRY RUN - er worden geen deliveries aangemaakt")

    results = []

    for order in orders:
        order_number = order.get("OrderNumber")
        customer = order.get("OrderedByName", "Onbekend")

        try:
            lines = get_undelivered_lines(client, order["OrderID"])

            if not lines:
                log.info(f"Order #{order_number} ({customer}): skip - geen openstaande regels")
                continue

            for line in lines:
                remaining = line["Quantity"] - line.get("QuantityDelivered", 0)
                log.info(f"  {line['ItemCode']} x{remaining}")

            if dry_run:
                results.append({
                    "order_number": order_number,
                    "customer": customer,
                    "success": True,
                    "dry_run": True,
                })
                continue

            response = create_goods_delivery(client, order, lines)
            delivery_number = response["d"]["DeliveryNumber"]
            log.info(f"Order #{order_number} ({customer}): delivery #{delivery_number} aangemaakt")

            results.append({
                "order_number": order_number,
                "customer": customer,
                "success": True,
                "delivery_number": delivery_number,
            })

        except Exception as e:
            log.error(f"Order #{order_number} ({customer}): FOUT - {e}")
            results.append({
                "order_number": order_number,
                "customer": customer,
                "success": False,
                "error": str(e),
            })

    return results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler("auto_delivery.log"),
            logging.StreamHandler(),
        ],
    )
    dry_run = "--dry-run" in sys.argv
    client = ExactClient()
    mode = "(DRY RUN) " if dry_run else ""
    log.info(f"=== Auto Delivery {mode}gestart ===")

    results = process_open_orders(client, dry_run=dry_run)

    success = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]
    log.info(f"Klaar: {len(success)} gelukt, {len(failed)} mislukt")
