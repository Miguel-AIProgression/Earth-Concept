from unittest.mock import MagicMock
from auto_delivery import get_open_kantoor_orders


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
