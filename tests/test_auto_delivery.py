from unittest.mock import MagicMock
import pytest
from auto_delivery import get_open_kantoor_orders, get_undelivered_lines, create_goods_delivery, process_open_orders


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


def test_process_open_orders_end_to_end():
    mock_client = MagicMock()
    mock_client.get.side_effect = [
        # Call 1: open orders
        [{"OrderID": "o1", "OrderNumber": 9556, "CreatorFullName": "Kantoor EARTH",
          "DeliveryStatus": 12, "Description": "2026.01/153.032",
          "DeliveryDate": "/Date(1775692800000)/", "OrderedByName": "Kreko B.V."}],
        # Call 2: order lines voor o1
        [{"ID": "l1", "ItemCode": "EW72306", "Quantity": 84, "QuantityDelivered": 0}],
    ]
    mock_client.post.return_value = {"d": {"EntryID": "gd-1", "DeliveryNumber": 7820}}

    results = process_open_orders(mock_client)

    assert len(results) == 1
    assert results[0]["order_number"] == 9556
    assert results[0]["success"] is True
    assert results[0]["delivery_number"] == 7820


def test_process_open_orders_skips_no_lines():
    mock_client = MagicMock()
    mock_client.get.side_effect = [
        [{"OrderID": "o1", "OrderNumber": 9999, "CreatorFullName": "Kantoor EARTH",
          "DeliveryStatus": 12, "Description": "test", "DeliveryDate": None,
          "OrderedByName": "Test B.V."}],
        [],  # geen openstaande regels
    ]

    results = process_open_orders(mock_client)
    assert len(results) == 0


def test_process_open_orders_handles_api_error():
    mock_client = MagicMock()
    mock_client.get.side_effect = [
        [{"OrderID": "o1", "OrderNumber": 9999, "CreatorFullName": "Kantoor EARTH",
          "DeliveryStatus": 12, "Description": "test", "DeliveryDate": None,
          "OrderedByName": "Test B.V."}],
        [{"ID": "l1", "ItemCode": "EW72306", "Quantity": 10, "QuantityDelivered": 0}],
    ]
    mock_client.post.side_effect = Exception("API error 500")

    results = process_open_orders(mock_client)

    assert len(results) == 1
    assert results[0]["success"] is False
    assert "API error" in results[0]["error"]
