"""Tests voor order_creator.py — builder + prepare, zonder live POST."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from order_creator import (
    build_salesorder_payload,
    compute_overall_confidence,
    prepare_order_for_review,
)


def _matched_line(item_id="item-1", code="EW-500", desc="Still 500ml", qty=10, price=1.2, conf=1.0):
    return {
        "line": {"item_code": code, "description": desc, "quantity": qty, "unit_price": price},
        "item_id": item_id,
        "item_code": code,
        "confidence": conf,
    }


def _mock_sb():
    sb = MagicMock()
    sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
    return sb


# ----- build_salesorder_payload -----


def test_build_salesorder_payload_basis():
    parsed = {"customer_reference": "PO-123", "description": "Bestelling mei"}
    payload = build_salesorder_payload(parsed, "acc-guid", [_matched_line()])
    assert payload["OrderedBy"] == "acc-guid"
    assert payload["YourRef"] == "PO-123"
    assert len(payload["SalesOrderLines"]) == 1
    line = payload["SalesOrderLines"][0]
    assert line["Item"] == "item-1"
    assert line["Quantity"] == 10
    assert line["UnitPrice"] == 1.2
    assert line["Description"] == "Still 500ml"


def test_build_salesorder_payload_datum_iso():
    parsed = {"customer_reference": "X", "delivery_date": "2026-05-01"}
    payload = build_salesorder_payload(parsed, "acc", [_matched_line()])
    assert payload["DeliveryDate"] == "2026-05-01T00:00:00"


def test_build_salesorder_payload_zonder_datum():
    parsed = {"customer_reference": "X"}
    payload = build_salesorder_payload(parsed, "acc", [_matched_line()])
    assert "DeliveryDate" not in payload


def test_build_salesorder_payload_missende_item_id_raised():
    parsed = {"customer_reference": "X"}
    bad = _matched_line(item_id=None)
    with pytest.raises(ValueError):
        build_salesorder_payload(parsed, "acc", [bad])


# ----- compute_overall_confidence -----


def test_compute_confidence_hoge_match():
    cust = {"id": "x", "confidence": 1.0}
    items = [_matched_line(conf=1.0)]
    conf = compute_overall_confidence(cust, items)
    assert conf == pytest.approx(1.0, abs=0.01)


def test_compute_confidence_nul_bij_missende_item():
    cust = {"id": "x", "confidence": 1.0}
    items = [_matched_line(item_id=None, conf=0.0)]
    assert compute_overall_confidence(cust, items) == 0.0


# ----- prepare_order_for_review -----


def test_prepare_order_for_review_ready():
    sb = _mock_sb()
    row = {
        "id": 42,
        "parsed_data": {
            "customer_name": "Minor Hotels",
            "customer_reference": "PO-9",
            "delivery_date": "2026-05-15",
            "lines": [
                {"item_code": "EW-500", "description": "Still", "quantity": 20, "unit_price": 1.0}
            ],
        },
    }

    with patch("order_creator.matcher") as mocked:
        mocked.match_customer.return_value = {"id": "acc-1", "name": "Minor Hotels", "confidence": 1.0}
        mocked.match_items.return_value = [
            {
                "line": row["parsed_data"]["lines"][0],
                "item_id": "item-1",
                "item_code": "EW-500",
                "confidence": 1.0,
                "source": "code",
            }
        ]
        updated = prepare_order_for_review(row, client=None, sb=sb)

    assert updated["parse_status"] == "ready_for_approval"
    parsed = updated["parsed_data"]
    assert parsed["match_confidence"] >= 0.9
    assert parsed["salesorder_payload"]["OrderedBy"] == "acc-1"
    assert parsed["matched_customer"]["id"] == "acc-1"
    sb.table.assert_called_with("incoming_orders")


def test_prepare_order_for_review_needs_review():
    sb = _mock_sb()
    row = {
        "id": 7,
        "parsed_data": {
            "customer_name": "Onbekend",
            "lines": [
                {"item_code": "UNKNOWN", "description": "Iets onduidelijks", "quantity": 1, "unit_price": 0}
            ],
        },
    }

    with patch("order_creator.matcher") as mocked:
        mocked.match_customer.return_value = None
        mocked.match_items.return_value = [
            {
                "line": row["parsed_data"]["lines"][0],
                "item_id": None,
                "item_code": None,
                "confidence": 0.0,
            }
        ]
        updated = prepare_order_for_review(row, client=None, sb=sb)

    assert updated["parse_status"] == "needs_review"
    parsed = updated["parsed_data"]
    assert parsed["match_confidence"] == 0.0
    assert parsed["salesorder_payload"] is None
