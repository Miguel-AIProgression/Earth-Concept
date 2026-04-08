from unittest.mock import MagicMock
import pytest
from auto_delivery import get_open_kantoor_orders, get_undelivered_lines, create_goods_delivery


def test_get_open_kantoor_orders_filters_correctly():
    """Retourneert alleen orders van Kantoor EARTH met DeliveryStatus 12."""
    mock_client = MagicMock()
    mock_client.get.return_value = [
        {"OrderNumber": 9527, "CreatorFullName": "Kantoor EARTH", "DeliveryStatus": 12},
        {"OrderNumber": 9545, "CreatorFullName": "Patrick de Nekker", "DeliveryStatus": 12},
        {"OrderNumber": 9537, "CreatorFullName": "Kantoor EARTH", "DeliveryStatus": 21},
    ]
    result = get_open_kantoor_orders(mock_client)
    assert len(result) == 1
    assert result[0]["OrderNumber"] == 9527


def test_get_open_kantoor_orders_empty():
    """Geen orders -> lege lijst."""
    mock_client = MagicMock()
    mock_client.get.return_value = []
    result = get_open_kantoor_orders(mock_client)
    assert result == []


def test_get_undelivered_lines_filters_delivered():
    mock_client = MagicMock()
    mock_client.get.return_value = [
        {"ID": "line-1", "ItemCode": "EW72306", "Quantity": 84, "QuantityDelivered": 0},
        {"ID": "line-2", "ItemCode": "EW72310", "Quantity": 50, "QuantityDelivered": 50},
    ]
    result = get_undelivered_lines(mock_client, "order-id-123")
    assert len(result) == 1
    assert result[0]["ID"] == "line-1"


def test_get_undelivered_lines_partial_delivery():
    """Gedeeltelijk afgeleverde regels moeten wel mee."""
    mock_client = MagicMock()
    mock_client.get.return_value = [
        {"ID": "line-1", "ItemCode": "EW72306", "Quantity": 84, "QuantityDelivered": 40},
    ]
    result = get_undelivered_lines(mock_client, "order-id-123")
    assert len(result) == 1


def test_create_goods_delivery_payload():
    mock_client = MagicMock()
    mock_client.post.return_value = {"d": {"EntryID": "gd-1", "DeliveryNumber": 7820}}

    order = {
        "OrderID": "order-123",
        "OrderNumber": 9527,
        "Description": "4600130365",
        "DeliveryDate": "/Date(1775692800000)/",
    }
    lines = [
        {"ID": "line-1", "ItemCode": "EW72306", "Quantity": 84, "QuantityDelivered": 0},
        {"ID": "line-2", "ItemCode": "EW72310", "Quantity": 50, "QuantityDelivered": 20},
    ]

    result = create_goods_delivery(mock_client, order, lines)

    call_args = mock_client.post.call_args
    assert call_args[0][0] == "/salesorder/GoodsDeliveries"

    payload = call_args[0][1]
    assert len(payload["GoodsDeliveryLines"]) == 2
    assert payload["GoodsDeliveryLines"][0]["SalesOrderLineID"] == "line-1"
    assert payload["GoodsDeliveryLines"][0]["QuantityDelivered"] == 84
    assert payload["GoodsDeliveryLines"][1]["QuantityDelivered"] == 30  # 50 - 20


def test_create_goods_delivery_empty_lines_raises():
    mock_client = MagicMock()
    with pytest.raises(ValueError):
        create_goods_delivery(mock_client, {"OrderNumber": 1}, [])
