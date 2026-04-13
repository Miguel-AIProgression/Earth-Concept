"""Tests voor order_creator.py — builder + matcher, zonder live POST."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from order_creator import (
    build_salesorder_payload,
    compute_overall_confidence,
    match_customer,
    match_items,
    prepare_order_for_review,
)


def _mock_client(side_effects):
    """Maak een mock client waarbij .get() side_effects in volgorde retourneert."""
    client = MagicMock()
    client.get.side_effect = list(side_effects)
    return client


# ----- match_customer -----

def test_match_customer_exact_hit():
    client = _mock_client([
        [{"ID": "guid-1", "Name": "Earth Water", "Code": "EW001"}],
    ])
    res = match_customer(client, "Earth Water")
    assert res == {"id": "guid-1", "name": "Earth Water", "confidence": 1.0}
    client.post.assert_not_called()


def test_match_customer_fuzzy_fallback():
    client = _mock_client([
        [],  # exact: geen hit
        [
            {"ID": "g2", "Name": "Earth Water Partner BV", "Code": "EWP"},
            {"ID": "g3", "Name": "Earth Water Logistics International", "Code": "EWL"},
        ],
    ])
    res = match_customer(client, "Earth")
    assert res["confidence"] == 0.7
    # kortste naam = beste kandidaat
    assert res["id"] == "g2"
    client.post.assert_not_called()


def test_match_customer_geen_match():
    client = _mock_client([[], []])
    assert match_customer(client, "Onbekende BV") is None
    client.post.assert_not_called()


def test_match_customer_quote_escape():
    client = _mock_client([
        [{"ID": "g", "Name": "O'Reilly", "Code": "OR"}],
    ])
    match_customer(client, "O'Reilly")
    args, kwargs = client.get.call_args_list[0]
    assert "O''Reilly" in kwargs["params"]["$filter"]
    client.post.assert_not_called()


# ----- match_items -----

def test_match_items_op_code():
    client = _mock_client([
        [{"ID": "item-1", "Code": "EW-500", "Description": "Still 500ml"}],
    ])
    lines = [{"item_code": "EW-500", "description": "Still 500ml", "quantity": 10, "unit_price": 1.2}]
    res = match_items(client, lines)
    assert res[0]["item_id"] == "item-1"
    assert res[0]["confidence"] == 1.0
    client.post.assert_not_called()


def test_match_items_fallback_description():
    client = _mock_client([
        [{"ID": "item-2", "Code": "EW-SPARK", "Description": "Sparkling 330ml can"}],
    ])
    lines = [{"description": "Sparkling 330ml can", "quantity": 5, "unit_price": 0.9}]
    res = match_items(client, lines)
    assert res[0]["item_id"] == "item-2"
    assert res[0]["confidence"] == 0.6
    args, kwargs = client.get.call_args_list[0]
    assert "substringof" in kwargs["params"]["$filter"]
    client.post.assert_not_called()


def test_match_items_geen_match():
    client = _mock_client([[], []])
    lines = [{"item_code": "NOPE", "description": "Onbekend product X", "quantity": 1, "unit_price": 0}]
    res = match_items(client, lines)
    assert res[0]["item_id"] is None
    assert res[0]["confidence"] == 0.0
    client.post.assert_not_called()


# ----- build_salesorder_payload -----

def _matched_line(item_id="item-1", code="EW-500", desc="Still 500ml", qty=10, price=1.2, conf=1.0):
    return {
        "line": {"item_code": code, "description": desc, "quantity": qty, "unit_price": price},
        "item_id": item_id,
        "item_code": code,
        "confidence": conf,
    }


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


def test_build_salesorder_payload_datum_odata():
    parsed = {"customer_reference": "X", "delivery_date": "2026-05-01"}
    payload = build_salesorder_payload(parsed, "acc", [_matched_line()])
    expected_ms = int(datetime.strptime("2026-05-01", "%Y-%m-%d").timestamp() * 1000)
    assert payload["DeliveryDate"] == f"/Date({expected_ms})/"


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

def _mock_sb():
    sb = MagicMock()
    sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
    return sb


def test_prepare_order_for_review_ready():
    client = _mock_client([
        [{"ID": "acc-1", "Name": "Minor Hotels", "Code": "MH"}],       # exact customer hit
        [{"ID": "item-1", "Code": "EW-500", "Description": "Still"}],  # item code hit
    ])
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
    updated = prepare_order_for_review(row, client, sb)
    assert updated["parse_status"] == "ready_for_approval"
    parsed = updated["parsed_data"]
    assert parsed["match_confidence"] >= 0.9
    assert parsed["salesorder_payload"]["OrderedBy"] == "acc-1"
    assert parsed["matched_customer"]["id"] == "acc-1"
    client.post.assert_not_called()
    sb.table.assert_called_with("incoming_orders")


def test_prepare_order_for_review_needs_review():
    client = _mock_client([
        [],  # exact customer miss
        [{"ID": "acc-2", "Name": "Minor Hotels International Group", "Code": "MHI"}],  # fuzzy
        [],  # item code miss
        [],  # item description miss
    ])
    sb = _mock_sb()
    row = {
        "id": 7,
        "parsed_data": {
            "customer_name": "Minor",
            "lines": [
                {"item_code": "UNKNOWN", "description": "Iets onduidelijks", "quantity": 1, "unit_price": 0}
            ],
        },
    }
    updated = prepare_order_for_review(row, client, sb)
    assert updated["parse_status"] == "needs_review"
    parsed = updated["parsed_data"]
    assert parsed["match_confidence"] == 0.0
    assert parsed["salesorder_payload"] is None
    client.post.assert_not_called()
