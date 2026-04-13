"""Tests voor order_parser.py — alle Claude API calls gemockt."""
import json
from unittest.mock import MagicMock

import pytest

from order_parser import parse_order, parse_incoming_order


FULL_REPLY = {
    "customer_name": "Minor Hotels",
    "customer_reference": "4600122152",
    "delivery_date": "2026-04-20",
    "delivery_address": {
        "street": "Hoofdstraat 1",
        "zip": "1000 AA",
        "city": "Amsterdam",
        "country": "NL",
    },
    "lines": [
        {
            "description": "Earth Water Still 500ml",
            "item_code": "EW-500-S",
            "quantity": 10,
            "unit": "doos",
            "unit_price": 12.50,
        }
    ],
    "notes": "Afleveren tussen 9-12u",
    "confidence": 0.92,
}


def _mock_client(reply_text):
    client = MagicMock()
    response = MagicMock()
    block = MagicMock()
    block.text = reply_text if isinstance(reply_text, str) else json.dumps(reply_text)
    response.content = [block]
    client.messages.create.return_value = response
    return client


def test_parse_text_basis():
    client = _mock_client(FULL_REPLY)
    result = parse_order(body_text="Bestelling: 10 dozen water", client=client)
    assert result["customer_name"] == "Minor Hotels"
    assert result["customer_reference"] == "4600122152"
    assert result["lines"][0]["item_code"] == "EW-500-S"
    assert result["confidence"] == 0.92


def test_parse_lege_input_raised():
    client = _mock_client(FULL_REPLY)
    with pytest.raises(ValueError):
        parse_order(client=client)


def test_parse_ongeldige_json_raised():
    client = _mock_client("geen JSON hier")
    with pytest.raises(ValueError):
        parse_order(body_text="iets", client=client)


def test_parse_json_in_markdown_fences():
    fenced = "```json\n" + json.dumps(FULL_REPLY) + "\n```"
    client = _mock_client(fenced)
    result = parse_order(body_text="iets", client=client)
    assert result["customer_name"] == "Minor Hotels"


def test_missende_velden_gedefault():
    client = _mock_client({"customer_name": "X"})
    result = parse_order(body_text="iets", client=client)
    assert result["customer_name"] == "X"
    assert result["lines"] == []
    assert result["confidence"] == 0.0


def test_parse_incoming_order_zet_status_parsed():
    client = _mock_client(FULL_REPLY)
    sb = MagicMock()
    row = {
        "id": "abc",
        "body_text": "Bestelling",
        "body_html": None,
        "attachments": [],
    }
    result = parse_incoming_order(row, sb, client=client)
    assert result["parse_status"] == "parsed"
    assert result["parsed_data"]["customer_name"] == "Minor Hotels"
    sb.table.assert_called_with("incoming_orders")


def test_parse_incoming_order_needs_review_bij_lage_confidence():
    low = dict(FULL_REPLY, confidence=0.5)
    client = _mock_client(low)
    sb = MagicMock()
    row = {"id": "abc", "body_text": "x", "body_html": None, "attachments": []}
    result = parse_incoming_order(row, sb, client=client)
    assert result["parse_status"] == "needs_review"


def test_parse_incoming_order_failed_bij_exception():
    client = _mock_client("geen JSON")
    sb = MagicMock()
    row = {"id": "abc", "body_text": "x", "body_html": None, "attachments": []}
    result = parse_incoming_order(row, sb, client=client)
    assert result["parse_status"] == "failed"
    assert result["error"]


def test_pdf_download_uit_storage():
    client = _mock_client(FULL_REPLY)
    sb = MagicMock()
    sb.storage.from_.return_value.download.return_value = b"%PDF-fake-bytes"
    row = {
        "id": "abc",
        "body_text": None,
        "body_html": None,
        "attachments": [{"storage_path": "abc/file.pdf", "filename": "file.pdf"}],
    }
    parse_incoming_order(row, sb, client=client)
    sb.storage.from_.assert_called_with("order-attachments")
    sb.storage.from_.return_value.download.assert_called_with("abc/file.pdf")
