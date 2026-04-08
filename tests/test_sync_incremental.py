import json
import os
from unittest.mock import MagicMock, patch
import pytest

from sync_incremental import (
    load_last_sync,
    save_last_sync,
    fetch_modified_orders,
    fetch_open_orders,
    sync_incremental,
)


@pytest.fixture
def state_file(tmp_path):
    """Gebruik een tijdelijk state bestand, zonder Supabase."""
    path = str(tmp_path / "sync_state.json")
    with patch("sync_incremental.STATE_FILE", path), \
         patch("sync_incremental._get_sb", return_value=None):
        yield path


def test_load_last_sync_no_file():
    with patch("sync_incremental.STATE_FILE", "/nonexistent/path.json"), \
         patch("sync_incremental._get_sb", return_value=None):
        assert load_last_sync() is None


def test_save_and_load_last_sync(state_file):
    save_last_sync("2026-04-08T12:00:00")
    assert load_last_sync() == "2026-04-08T12:00:00"


def test_fetch_modified_orders_uses_correct_filter():
    mock = MagicMock()
    mock.get.return_value = [{"OrderID": "o1", "OrderNumber": 9556}]

    result = fetch_modified_orders(mock, "2026-04-08T10:00:00")

    call_args = mock.get.call_args
    assert "Modified ge datetime'2026-04-08T10:00:00'" in call_args[1]["params"]["$filter"]
    assert len(result) == 1


def test_fetch_open_orders_uses_correct_filter():
    mock = MagicMock()
    mock.get.return_value = [{"OrderID": "o1"}]

    result = fetch_open_orders(mock)

    call_args = mock.get.call_args
    assert "DeliveryStatus ne 21" in call_args[1]["params"]["$filter"]
    assert len(result) == 1


def test_sync_incremental_initial_run(state_file):
    """Eerste run haalt alle 2026 orders op."""
    mock_exact = MagicMock()
    mock_exact.get.return_value = [
        _fake_order(9556, "Kreko B.V.", "Kantoor EARTH"),
        _fake_order(9545, "Radisson Blu", "Patrick de Nekker"),
    ]

    result = sync_incremental(exact=mock_exact, dry_run=True)

    assert result["orders"] == 2
    assert result["dry_run"] is True
    # Eerste call moet alle 2026 orders ophalen
    first_call = mock_exact.get.call_args_list[0]
    assert "2026-01-01" in first_call[1]["params"]["$filter"]


def test_sync_incremental_deduplicates(state_file):
    """Orders die in beide queries voorkomen worden gededupliceerd."""
    save_last_sync("2026-04-08T10:00:00")

    mock_exact = MagicMock()
    shared_order = _fake_order(9556, "Kreko B.V.", "Kantoor EARTH")
    only_modified = _fake_order(9545, "Radisson Blu", "Patrick de Nekker")
    only_open = _fake_order(9550, "Vesper Hotel", "Patrick de Nekker")

    mock_exact.get.side_effect = [
        [shared_order, only_modified],  # modified
        [shared_order, only_open],      # open
    ]

    result = sync_incremental(exact=mock_exact, dry_run=True)

    # 3 unieke orders, niet 4
    assert result["orders"] == 3


def test_sync_incremental_saves_state(state_file):
    """Na succesvolle sync wordt de timestamp opgeslagen."""
    mock_exact = MagicMock()
    mock_exact.get.return_value = []

    mock_sb_instance = MagicMock()
    mock_sb_instance.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[])
    with patch("sync_incremental.create_client", return_value=mock_sb_instance), \
         patch("sync_incremental._get_sb", return_value=None):
        sync_incremental(exact=mock_exact, dry_run=False)

    assert load_last_sync() is not None


def _fake_order(number, customer, creator):
    return {
        "OrderID": f"order-{number}",
        "OrderNumber": number,
        "OrderDate": "/Date(1775692800000)/",
        "DeliveryStatus": 12,
        "DeliveryStatusDescription": "Open",
        "InvoiceStatus": 0,
        "InvoiceStatusDescription": "",
        "CreatorFullName": creator,
        "OrderedByName": customer,
        "Description": f"Order {number}",
        "YourRef": "",
        "DeliveryDate": None,
        "AmountDC": 100.00,
        "Modified": "/Date(1775692800000)/",
    }
