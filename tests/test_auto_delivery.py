from unittest.mock import MagicMock
from auto_delivery import get_open_kantoor_orders, get_undelivered_lines


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
