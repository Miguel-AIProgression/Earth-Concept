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


def test_build_salesorder_payload_laat_unitprice_weg_bij_nul_of_null():
    parsed = {"customer_reference": "X"}

    # unit_price == 0 -> UnitPrice weg (Exact pakt default).
    line_zero = _matched_line(price=0)
    payload = build_salesorder_payload(parsed, "acc", [line_zero])
    assert "UnitPrice" not in payload["SalesOrderLines"][0]

    # unit_price ontbreekt -> UnitPrice weg.
    line_missing = _matched_line()
    line_missing["line"].pop("unit_price", None)
    payload = build_salesorder_payload(parsed, "acc", [line_missing])
    assert "UnitPrice" not in payload["SalesOrderLines"][0]

    # unit_price is None -> UnitPrice weg.
    line_none = _matched_line()
    line_none["line"]["unit_price"] = None
    payload = build_salesorder_payload(parsed, "acc", [line_none])
    assert "UnitPrice" not in payload["SalesOrderLines"][0]


def test_build_salesorder_payload_echte_prijs_blijft():
    parsed = {"customer_reference": "X"}
    line = _matched_line(price=2.5)
    payload = build_salesorder_payload(parsed, "acc", [line])
    assert payload["SalesOrderLines"][0]["UnitPrice"] == 2.5


def test_build_salesorder_payload_missende_item_id_raised():
    parsed = {"customer_reference": "X"}
    bad = _matched_line(item_id=None)
    with pytest.raises(ValueError):
        build_salesorder_payload(parsed, "acc", [bad])


def test_build_salesorder_payload_description_is_po_niet_willekeurige_tekst():
    """Description moet altijd het PO-nummer zijn.

    Regressie: Claude retourneert soms een 'description'-veld buiten het
    schema om, met een willekeurige zin uit de mail/PDF ('Incoterm:
    Delivered Duty Paid...', 'Ordernummer X vermelden op afleverbon...').
    Die kwam vroeger als Description in Exact terecht. We moeten die
    negeren en altijd het customer_reference kiezen.
    """
    parsed = {
        "customer_reference": "2604220003",
        "description": "Incoterm: Delivered Duty Paid. Betaling binnen 30 dagen",
    }
    payload = build_salesorder_payload(parsed, "acc", [_matched_line()])
    assert payload["Description"] == "2604220003"


def test_build_salesorder_payload_description_fallback_als_geen_po():
    """Zonder customer_reference mag de description-parameter alsnog dienen."""
    parsed = {}
    payload = build_salesorder_payload(parsed, "acc", [_matched_line()], description="Handmatig")
    assert payload["Description"] == "Handmatig"

    payload = build_salesorder_payload(parsed, "acc", [_matched_line()])
    assert payload["Description"] == "Bestelling"


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


def test_prepare_order_for_review_auto_approved():
    """Hoge confidence + trusted items => direct 'approved' (auto-gate)."""
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
        mocked.match_customer.return_value = {
            "id": "acc-1", "name": "Minor Hotels", "confidence": 1.0, "source": "exact",
        }
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

    assert updated["parse_status"] == "approved"
    parsed = updated["parsed_data"]
    assert parsed["match_confidence"] >= 0.85
    assert parsed["salesorder_payload"]["OrderedBy"] == "acc-1"
    assert parsed["matched_customer"]["id"] == "acc-1"
    sb.table.assert_called_with("incoming_orders")


def test_prepare_order_for_review_fuzzy_klant_needs_review():
    """Fuzzy klant-match mag nooit auto-approve, ook niet bij hoge totaal-score.

    Waargebeurd: 'Inbev Nederland NV' matchte op 'Independent Films
    Nederland B.V.' met 0.855; items waren code-match 1.0 -> overall 0.942,
    ruim boven 0.85. Zonder deze guard ging de order naar de verkeerde
    relatie in Exact.
    """
    sb = _mock_sb()
    row = {
        "id": 77,
        "parsed_data": {
            "customer_name": "Inbev Nederland NV",
            "lines": [
                {"item_code": "EW-500", "description": "Still", "quantity": 10, "unit_price": 1.0}
            ],
        },
    }

    with patch("order_creator.matcher") as mocked:
        mocked.match_customer.return_value = {
            "id": "wrong-acc",
            "name": "Independent Films Nederland B.V.",
            "confidence": 0.855,
            "source": "fuzzy",
        }
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

    assert updated["parse_status"] == "needs_review"
    assert updated["parsed_data"]["match_confidence"] >= 0.85


def test_prepare_order_for_review_zonder_prijs_needs_review():
    """Hoge confidence + trusted code, maar regel zonder prijs => needs_review."""
    sb = _mock_sb()
    row = {
        "id": 51,
        "parsed_data": {
            "customer_name": "Minor Hotels",
            "lines": [
                {"item_code": "EW-500", "description": "Still", "quantity": 20, "unit_price": 0}
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

    assert updated["parse_status"] == "needs_review"


def test_prepare_order_for_review_onder_drempel():
    """Confidence 0.84 => needs_review, ook al is het item trusted."""
    sb = _mock_sb()
    row = {
        "id": 99,
        "parsed_data": {
            "customer_name": "Twijfelklant",
            "lines": [
                {"item_code": "EW-500", "description": "Still", "quantity": 5, "unit_price": 1.0}
            ],
        },
    }

    with patch("order_creator.matcher") as mocked:
        # 0.6*0.4 + 1.0*0.6 = 0.84, net onder de gate.
        mocked.match_customer.return_value = {
            "id": "acc-2", "name": "Twijfelklant", "confidence": 0.6, "source": "exact",
        }
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

    assert updated["parse_status"] == "needs_review"


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
