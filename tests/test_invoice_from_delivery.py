"""Tests voor invoice_from_delivery module."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from invoice_from_delivery import (
    build_invoice_payload,
    load_delivery_excel,
    match_deliveries_to_orders,
    process_delivery_file,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_XLS = REPO_ROOT / "EARTHWATER Order Exportbericht 2021 (2).xls"


def _make_order(order_number="SO001", order_id="order-guid-1", lines=None):
    return {
        "OrderNumber": order_number,
        "OrderID": order_id,
        "lines": lines
        or [
            {
                "ItemCode": "ITEM-A",
                "ItemId": "item-a-guid",
                "Quantity": 120,
                "UnitPrice": 10.0,
                "Id": "line-1",
            }
        ],
    }


def _make_delivery(
    order_number="SO001",
    item_code="ITEM-A",
    quantity=120,
    unit_price=10.0,
    your_ref="REF-1",
):
    return {
        "order_number": order_number,
        "invoice_number": None,
        "customer_code": "C001",
        "customer_name": "Klant",
        "item_code": item_code,
        "description": "Fles 500ml",
        "quantity_delivered": quantity,
        "unit_price": unit_price,
        "net_price": quantity * unit_price,
        "vat_code": "VH",
        "your_ref": your_ref,
        "order_date": "2021-01-01",
        "unit": "CS",
    }


@pytest.mark.skipif(not REAL_XLS.exists(), reason="Voorbeeld-xls niet in repo-root")
def test_load_delivery_excel_real_file():
    rows = load_delivery_excel(REAL_XLS)
    assert len(rows) >= 1
    assert any(r.get("order_number") and r.get("item_code") for r in rows)


def test_match_perfect():
    deliveries = [_make_delivery(quantity=120)]
    orders = [_make_order()]
    matches, discrepancies = match_deliveries_to_orders(deliveries, orders)
    assert len(matches) == 1
    assert discrepancies == []
    m = matches[0]
    assert m["order_number"] == "SO001"
    assert m["order_id"] == "order-guid-1"
    assert m["has_shortage"] is False
    assert len(m["lines"]) == 1
    assert m["lines"][0]["shortage"] == 0
    assert m["lines"][0]["delivered"] == 120
    assert m["lines"][0]["ordered"] == 120


def test_match_shortage():
    deliveries = [_make_delivery(quantity=100)]
    orders = [_make_order()]
    matches, discrepancies = match_deliveries_to_orders(deliveries, orders)
    assert len(matches) == 1
    assert discrepancies == []
    m = matches[0]
    assert m["has_shortage"] is True
    assert m["lines"][0]["shortage"] == 20
    assert m["lines"][0]["delivered"] == 100


def test_match_excess():
    deliveries = [_make_delivery(quantity=130)]
    orders = [_make_order()]
    matches, discrepancies = match_deliveries_to_orders(deliveries, orders)
    # excess leidt tot discrepancy, NIET match
    assert all(
        not any(l["item_code"] == "ITEM-A" for l in m["lines"]) for m in matches
    ) or matches == []
    assert any(d["type"] == "excess_delivery" for d in discrepancies)


def test_match_no_matching_order():
    deliveries = [_make_delivery(order_number="SO999")]
    orders = [_make_order(order_number="SO001")]
    matches, discrepancies = match_deliveries_to_orders(deliveries, orders)
    assert matches == []
    assert len(discrepancies) == 1
    assert discrepancies[0]["type"] == "no_matching_order"
    assert discrepancies[0]["order_number"] == "SO999"


def test_match_no_matching_line():
    deliveries = [_make_delivery(item_code="ITEM-X")]
    orders = [_make_order()]
    matches, discrepancies = match_deliveries_to_orders(deliveries, orders)
    assert any(d["type"] == "no_matching_line" for d in discrepancies)


def test_build_invoice_payload_basis():
    match = {
        "order_number": "SO001",
        "order_id": "order-guid-1",
        "your_ref": "REF-1",
        "lines": [
            {
                "item_code": "ITEM-A",
                "item_id": "item-a-guid",
                "ordered": 120,
                "delivered": 120,
                "unit_price": 10.0,
                "description": "Fles",
                "line_id": "line-1",
                "shortage": 0,
            }
        ],
        "has_shortage": False,
        "total_net": 1200.0,
    }
    payload = build_invoice_payload(match, account_id="acct-guid")
    assert payload["InvoiceTo"] == "acct-guid"
    assert payload["OrderedBy"] == "acct-guid"
    assert payload["YourRef"] == "REF-1"
    assert len(payload["SalesInvoiceLines"]) == 1
    line = payload["SalesInvoiceLines"][0]
    assert line["Item"] == "item-a-guid"
    assert line["Quantity"] == 120
    assert line["UnitPrice"] == 10.0


def test_build_invoice_payload_skipt_nul_regels():
    match = {
        "order_number": "SO001",
        "order_id": "order-guid-1",
        "your_ref": "REF-1",
        "lines": [
            {
                "item_code": "ITEM-A",
                "item_id": "item-a-guid",
                "ordered": 120,
                "delivered": 0,
                "unit_price": 10.0,
                "description": "Fles",
                "line_id": "line-1",
                "shortage": 120,
            },
            {
                "item_code": "ITEM-B",
                "item_id": "item-b-guid",
                "ordered": 10,
                "delivered": 10,
                "unit_price": 5.0,
                "description": "Fles B",
                "line_id": "line-2",
                "shortage": 0,
            },
        ],
        "has_shortage": True,
        "total_net": 50.0,
    }
    payload = build_invoice_payload(match, account_id="acct-guid")
    assert len(payload["SalesInvoiceLines"]) == 1
    assert payload["SalesInvoiceLines"][0]["Item"] == "item-b-guid"


def test_process_delivery_file_stats(tmp_path, monkeypatch):
    deliveries = [
        _make_delivery(order_number="SO001", quantity=120),  # perfect
        _make_delivery(order_number="SO002", quantity=80),   # shortage
        _make_delivery(order_number="SO999", quantity=10),   # no match
    ]
    orders = [
        _make_order(order_number="SO001"),
        _make_order(order_number="SO002", order_id="order-guid-2"),
    ]

    def fake_load(path, sheet="import"):
        return deliveries

    monkeypatch.setattr(
        "invoice_from_delivery.load_delivery_excel", fake_load
    )

    sb = MagicMock()
    stats = process_delivery_file("dummy.xls", orders, sb=sb)
    assert stats["matched"] == 2
    assert stats["shortages"] == 1
    assert stats["discrepancies"] == 1
    assert stats["ready"] == 1


def test_process_delivery_file_schrijft_holds_met_status(monkeypatch):
    deliveries = [
        _make_delivery(order_number="SO001", quantity=120),  # perfect -> ready
        _make_delivery(order_number="SO002", quantity=80),   # shortage -> review
    ]
    orders = [
        _make_order(order_number="SO001"),
        _make_order(order_number="SO002", order_id="order-guid-2"),
    ]
    monkeypatch.setattr(
        "invoice_from_delivery.load_delivery_excel",
        lambda path, sheet="import": deliveries,
    )

    sb = MagicMock()
    process_delivery_file("dummy.xls", orders, sb=sb)

    # verzamel alle upsert calls
    upsert_calls = sb.table.return_value.upsert.call_args_list
    statuses = []
    for call in upsert_calls:
        payload = call.args[0] if call.args else call.kwargs.get("json")
        if isinstance(payload, list):
            for p in payload:
                statuses.append(p.get("status"))
        else:
            statuses.append(payload.get("status"))
    assert "ready_to_invoice" in statuses
    assert "review" in statuses
    # controleer dat tabel 'invoice_holds' is gebruikt
    assert any(
        c.args[0] == "invoice_holds" for c in sb.table.call_args_list
    )


def test_geen_live_post(monkeypatch):
    # Import module; verifieer dat er geen ExactClient / requests.post gebruikt wordt
    import invoice_from_delivery as mod

    assert not hasattr(mod, "ExactClient") or mod.__dict__.get("ExactClient") is None
    # Geen verwijzing naar requests.post in module code
    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "requests.post" not in src
    assert "client.post" not in src


def test_edi_klant_geskipt():
    delivery = [
        {"order_number": "SO001", "customer_name": "Bidfood Geleen (EW-EDI)",
         "item_code": "ITEM-A", "quantity_delivered": 120, "unit_price": 10.0},
        {"order_number": "SO002", "customer_name": "Minor Hotels",
         "item_code": "ITEM-A", "quantity_delivered": 50, "unit_price": 10.0},
    ]
    orders = [
        _make_order("SO001"),
        _make_order("SO002", order_id="order-guid-2"),
    ]
    with patch("invoice_from_delivery.is_edi_customer",
               side_effect=lambda n: n and "EW-EDI" in n):
        matches, discrepancies = match_deliveries_to_orders(delivery, orders)
    order_numbers = [m["order_number"] for m in matches]
    assert order_numbers == ["SO002"]
    assert not any(d["order_number"] == "SO001" for d in discrepancies)
