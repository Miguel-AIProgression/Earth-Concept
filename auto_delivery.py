"""Automatisch GoodsDeliveries aanmaken voor Kantoor EARTH (Semso/EDI) orders."""

import sys
import logging

from exact_client import ExactClient

CREATOR_KANTOOR = "Kantoor EARTH"

log = logging.getLogger(__name__)


def get_open_kantoor_orders(client):
    """Haal alle open orders op die zijn aangemaakt door Kantoor EARTH."""
    orders = client.get("/salesorder/SalesOrders", params={
        "$filter": "DeliveryStatus eq 12",
        "$select": "OrderID,OrderNumber,OrderDate,DeliveryStatus,"
                   "CreatorFullName,OrderedByName,Description,YourRef,DeliveryDate",
        "$orderby": "OrderDate desc",
    })
    return [o for o in orders
            if o.get("CreatorFullName") == CREATOR_KANTOOR
            and o.get("DeliveryStatus") == 12]


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
