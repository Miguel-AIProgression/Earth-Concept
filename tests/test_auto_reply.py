"""Tests voor auto_reply.py — diagnose, suggesties, mail-content, SMTP."""

from unittest.mock import MagicMock

import pytest

import auto_reply


# ---------- helpers ----------


def _sb_with_items(items):
    sb = MagicMock()

    def table(name):
        t = MagicMock()
        if name == "exact_items":
            t.select.return_value.range.return_value.execute.return_value = MagicMock(data=items)
        return t

    sb.table.side_effect = table
    return sb


# ---------- diagnose_order ----------


def test_diagnose_parse_failed():
    row = {
        "parse_status": "failed",
        "error": "Error code: 400 - iets",
        "parsed_data": None,
    }
    d = auto_reply.diagnose_order(row)
    assert d.parse_failed
    assert d.has_problems
    assert "400" in (d.parse_error or "")


def test_diagnose_no_lines():
    row = {
        "parse_status": "needs_review",
        "parsed_data": {
            "customer_name": "X",
            "lines": [],
            "matched_customer": {"id": "a1", "name": "X", "confidence": 1.0, "source": "exact"},
            "matched_items": [],
        },
    }
    d = auto_reply.diagnose_order(row)
    assert d.no_lines
    assert not d.customer_unknown
    assert not d.items_unmatched


def test_diagnose_customer_unknown_geen_match():
    row = {
        "parse_status": "needs_review",
        "parsed_data": {
            "customer_name": "Iets",
            "lines": [{"description": "x", "quantity": 1}],
            "matched_customer": None,
            "matched_items": [{"line": {"description": "x"}, "item_id": "i1"}],
        },
    }
    d = auto_reply.diagnose_order(row)
    assert d.customer_unknown
    assert d.customer_best_guess is None


def test_diagnose_customer_low_confidence():
    row = {
        "parse_status": "needs_review",
        "parsed_data": {
            "customer_name": "Park Inn",
            "lines": [{"description": "x"}],
            "matched_customer": {"id": "a1", "name": "Guess", "confidence": 0.82, "source": "fuzzy"},
            "matched_items": [{"line": {"description": "x"}, "item_id": "i1"}],
        },
    }
    d = auto_reply.diagnose_order(row)
    assert d.customer_unknown
    assert d.customer_best_guess == "Guess"
    assert abs(d.customer_confidence - 0.82) < 1e-9


def test_diagnose_customer_high_confidence_no_problem():
    row = {
        "parse_status": "needs_review",
        "parsed_data": {
            "customer_name": "X",
            "lines": [{"description": "x"}],
            "matched_customer": {"id": "a1", "name": "X", "confidence": 0.95, "source": "fuzzy"},
            "matched_items": [{"line": {"description": "x"}, "item_id": "i1"}],
        },
    }
    d = auto_reply.diagnose_order(row)
    assert not d.customer_unknown
    assert not d.items_unmatched
    assert not d.has_problems


def test_diagnose_items_unmatched_met_suggesties():
    items = [
        {"id": "i1", "code": "EW72306", "description": "EARTH WATER STILL TETRA TOP OW 24X50CL",
         "description_normalized": "earth water still tetra top ow 24x50cl", "unit": "ST"},
        {"id": "i2", "code": "EW72310", "description": "EARTH WATER SPARKLING GLASS OW 12X75CL",
         "description_normalized": "earth water sparkling glass ow 12x75cl", "unit": "ST"},
    ]
    sb = _sb_with_items(items)
    row = {
        "parse_status": "needs_review",
        "parsed_data": {
            "customer_name": "X",
            "lines": [{"description": "Earth Water Still 24x50cl", "quantity": 10}],
            "matched_customer": {"id": "a1", "name": "X", "confidence": 1.0, "source": "exact"},
            "matched_items": [
                {"line": {"description": "Earth Water Still 24x50cl", "quantity": 10},
                 "item_id": None, "confidence": 0.0, "source": None},
            ],
        },
    }
    d = auto_reply.diagnose_order(row, sb=sb)
    assert len(d.items_unmatched) == 1
    ul = d.items_unmatched[0]
    assert ul.quantity == 10
    # Er moet minstens 1 suggestie zijn en de eerste moet EW72306 (still tetra) zijn.
    assert ul.suggestions
    assert ul.suggestions[0].code == "EW72306"


# ---------- gather_item_suggestions ----------


def test_gather_item_suggestions_via_code_typo():
    items = [
        {"id": "i1", "code": "EW9208", "description": "Radisson TT 50cl",
         "description_normalized": "radisson tt 50cl", "unit": "ST"},
    ]
    sb = _sb_with_items(items)
    # Klant typt bijna-correcte code — fuzzy op code moet dit vinden.
    sug = auto_reply.gather_item_suggestions(sb, {"item_code": "EW9207", "description": "iets"}, items_cache=items)
    assert sug
    assert sug[0].code == "EW9208"


def test_gather_item_suggestions_geen_resultaat():
    items = [
        {"id": "i1", "code": "ABC", "description": "Iets heel anders",
         "description_normalized": "iets heel anders", "unit": "ST"},
    ]
    sb = _sb_with_items(items)
    sug = auto_reply.gather_item_suggestions(
        sb, {"description": "kartonnen verhuisdoos bruin xxl"}, items_cache=items
    )
    assert sug == []


# ---------- build_reply ----------


def test_build_reply_bevat_alle_secties():
    row = {
        "subject": "Fwd: Bestelling",
        "parsed_data": {"customer_name": "Park Inn Leuven"},
    }
    d = auto_reply.Diagnosis(
        no_lines=True,
        customer_unknown=True,
        customer_best_guess="Exco Hotel",
        customer_confidence=0.82,
        items_unmatched=[
            auto_reply.UnmatchedLine(
                description="Earth Water Still 0.75l",
                quantity=35,
                item_code_in_mail=None,
                suggestions=[
                    auto_reply.ItemSuggestion(code="EW72310", description="Still glass", score=0.93),
                ],
            )
        ],
    )
    subject, body = auto_reply.build_reply(row, d)
    assert subject.startswith("Re: ")
    assert "Fwd: Bestelling" in subject
    assert "Park Inn Leuven" in body
    assert "Exco Hotel" in body
    assert "82%" in body
    assert "Earth Water Still 0.75l" in body
    assert "EW72310" in body
    assert "93%" in body


def test_build_reply_skipt_no_lines_bij_parse_failed():
    """Als parsing faalde, is no_lines irrelevant — we willen niet allebei tonen."""
    row = {"subject": "Fwd: X", "parsed_data": {}}
    d = auto_reply.Diagnosis(parse_failed=True, parse_error="boom", no_lines=True)
    subject, body = auto_reply.build_reply(row, d)
    assert "niet leesbaar" in body
    # no_lines-sectie heeft een specifieke bewoording die NIET mag verschijnen.
    assert "Forwards slaan bijlagen soms over" not in body


# ---------- send_auto_reply ----------


def test_send_auto_reply_threadt_op_message_id():
    """In-Reply-To en References zetten de reply in dezelfde thread."""
    sent = {}

    def sender(msg):
        sent["msg"] = msg

    row = {
        "id": "r1",
        "from_address": "patrick@earthwater.nl",
        "subject": "Fwd: X",
        "message_id": "<abcd@earthwater.nl>",
        "parsed_data": {"customer_name": "Y"},
    }
    d = auto_reply.Diagnosis(no_lines=True)
    ok = auto_reply.send_auto_reply(row, d, smtp_sender=sender)
    assert ok is True
    assert sent["msg"]["To"] == "patrick@earthwater.nl"
    assert sent["msg"]["In-Reply-To"] == "<abcd@earthwater.nl>"
    assert sent["msg"]["References"] == "<abcd@earthwater.nl>"
    assert sent["msg"]["Subject"].startswith("Re:")


def test_send_auto_reply_skip_zonder_from_address():
    called = {"n": 0}

    def sender(msg):
        called["n"] += 1

    row = {"id": "r1", "from_address": None, "subject": "X", "parsed_data": {}}
    ok = auto_reply.send_auto_reply(
        row, auto_reply.Diagnosis(parse_failed=True), smtp_sender=sender
    )
    assert ok is False
    assert called["n"] == 0


# ---------- maybe_send_auto_reply ----------


def test_maybe_send_skipt_als_al_verstuurd():
    row = {
        "id": "r1",
        "from_address": "p@x.nl",
        "parse_status": "failed",
        "error": "x",
        "parsed_data": None,
        "auto_reply_sent_at": "2026-04-20T10:00:00Z",
    }
    sb = MagicMock()
    sent = {"n": 0}
    res = auto_reply.maybe_send_auto_reply(
        row, sb, smtp_sender=lambda m: sent.__setitem__("n", sent["n"] + 1)
    )
    assert res["skipped_already_sent"] is True
    assert res["sent"] is False
    assert sent["n"] == 0


def test_maybe_send_stuurt_en_update_supabase():
    row = {
        "id": "r1",
        "from_address": "Patrick <patrick@earthwater.nl>",
        "subject": "Fwd: X",
        "message_id": "<abc@x.nl>",
        "parse_status": "failed",
        "error": "boom",
        "parsed_data": None,
        "auto_reply_sent_at": None,
    }
    sb = MagicMock()
    # Voor diagnose_order met parse_failed=True worden er geen items gefetchd,
    # maar voor de zekerheid zetten we de chain up.
    sb.table.return_value.select.return_value.range.return_value.execute.return_value = MagicMock(data=[])

    sent = {}
    res = auto_reply.maybe_send_auto_reply(
        row, sb, smtp_sender=lambda m: sent.setdefault("msg", m)
    )
    assert res["sent"] is True
    assert res["problems"] >= 1
    # Supabase-update is aangeroepen met auto_reply_sent_at.
    update_calls = [
        c for c in sb.table.return_value.update.call_args_list
        if "auto_reply_sent_at" in (c.args[0] if c.args else {})
    ]
    assert update_calls, "Er is geen update met auto_reply_sent_at geweest"


def test_maybe_send_geen_problemen_geen_reply():
    row = {
        "id": "r1",
        "from_address": "Patrick <patrick@earthwater.nl>",
        "parse_status": "needs_review",
        "parsed_data": {
            "customer_name": "X",
            "lines": [{"description": "x"}],
            "matched_customer": {"id": "a1", "name": "X", "confidence": 1.0, "source": "exact"},
            "matched_items": [{"line": {"description": "x"}, "item_id": "i1"}],
        },
        "auto_reply_sent_at": None,
    }
    sb = MagicMock()
    res = auto_reply.maybe_send_auto_reply(row, sb, smtp_sender=lambda m: None)
    assert res["sent"] is False
    assert res["problems"] == 0


# ---------- _smtp_config fallback ----------


def test_smtp_config_valt_terug_op_mail_credentials(monkeypatch):
    """Als SMTP_* env-vars ontbreken maar MAIL_USER/MAIL_PASS er zijn,
    valt auto-reply terug op diezelfde Gmail-credentials."""
    for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "SMTP_FROM"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("MAIL_HOST", "imap.gmail.com")
    monkeypatch.setenv("MAIL_USER", "orders@earthwater.nl")
    monkeypatch.setenv("MAIL_PASS", "app-password-123")

    cfg = auto_reply._smtp_config()
    assert cfg is not None
    assert cfg["host"] == "smtp.gmail.com"
    assert cfg["port"] == 587
    assert cfg["user"] == "orders@earthwater.nl"
    assert cfg["password"] == "app-password-123"
    assert cfg["from"] == "orders@earthwater.nl"


def test_smtp_config_geen_credentials_retourneert_none(monkeypatch):
    for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "SMTP_FROM",
              "MAIL_HOST", "MAIL_USER", "MAIL_PASS"):
        monkeypatch.delenv(k, raising=False)
    assert auto_reply._smtp_config() is None


# ---------- Forwarder-filter ----------


def test_is_from_forwarder_intern_domein(monkeypatch):
    """Elke @earthwater.nl-afzender is OK: Patrick, Thomas, info, etc."""
    monkeypatch.delenv("FORWARD_SENDER_ALLOWLIST", raising=False)
    monkeypatch.delenv("FORWARD_SENDER_DOMAIN", raising=False)
    assert auto_reply._is_from_forwarder("Patrick De Nekker <patrick@earthwater.nl>")
    assert auto_reply._is_from_forwarder("Thomas Van Amerom <thomas@earthwater.nl>")
    assert auto_reply._is_from_forwarder("info earthwater <info@earthwater.nl>")


def test_is_from_forwarder_reject_externe_afzender(monkeypatch):
    """Adressen buiten @earthwater.nl mogen nooit een auto-reply krijgen."""
    monkeypatch.delenv("FORWARD_SENDER_ALLOWLIST", raising=False)
    monkeypatch.delenv("FORWARD_SENDER_DOMAIN", raising=False)
    assert not auto_reply._is_from_forwarder("iemand@klant.nl")
    assert not auto_reply._is_from_forwarder("spoof@earthwater.nl.evil.com")
    assert not auto_reply._is_from_forwarder("")
    assert not auto_reply._is_from_forwarder(None)


def test_send_auto_reply_logt_naar_sent_emails():
    """Na een succesvolle send wordt een rij in sent_emails opgeslagen."""
    sb = MagicMock()
    inserted = {}

    def fake_insert(data):
        inserted["data"] = data
        m = MagicMock()
        m.execute.return_value = MagicMock(data=[data])
        return m

    sb.table.return_value.insert.side_effect = fake_insert

    row = {
        "id": "row-uuid",
        "from_address": "patrick@earthwater.nl",
        "subject": "Fwd: X",
        "message_id": "<abc@x.nl>",
        "parsed_data": {"customer_name": "Y"},
    }
    d = auto_reply.Diagnosis(no_lines=True)
    ok = auto_reply.send_auto_reply(row, d, smtp_sender=lambda m: None, sb=sb)
    assert ok is True
    assert inserted["data"]["type"] == "auto_reply"
    assert inserted["data"]["incoming_order_id"] == "row-uuid"
    assert inserted["data"]["to_address"] == "patrick@earthwater.nl"
    assert "Re:" in inserted["data"]["subject"]
    assert "Hoi Patrick" in inserted["data"]["body"]
    assert inserted["data"]["in_reply_to"] == "<abc@x.nl>"


def test_is_from_forwarder_allowlist_override(monkeypatch):
    """Expliciete FORWARD_SENDER_ALLOWLIST beperkt tot specifieke adressen."""
    monkeypatch.setenv("FORWARD_SENDER_ALLOWLIST", "patrick@earthwater.nl")
    assert auto_reply._is_from_forwarder("patrick@earthwater.nl")
    assert not auto_reply._is_from_forwarder("thomas@earthwater.nl")


def test_maybe_send_auto_reply_skipt_niet_forwarder():
    row = {
        "id": "r1",
        "from_address": "klant@extern.nl",
        "parse_status": "failed",
        "error": "boom",
        "parsed_data": None,
        "auto_reply_sent_at": None,
    }
    sb = MagicMock()
    sent = {"n": 0}
    res = auto_reply.maybe_send_auto_reply(
        row, sb, smtp_sender=lambda m: sent.__setitem__("n", sent["n"] + 1)
    )
    assert res["skipped_not_forwarder"] is True
    assert res["sent"] is False
    assert sent["n"] == 0


# ---------- Confirmation ----------


def test_build_confirmation_bevat_alle_velden():
    row = {
        "subject": "Fwd: Bestelling X",
        "message_id": "<origineel@x.nl>",
        "exact_order_id": "ABC-123",
        "parsed_data": {
            "matched_customer": {"id": "a1", "name": "Park Inn Leuven", "confidence": 0.9, "source": "fuzzy"},
            "customer_reference": "PO-99",
            "delivery_date": "2026-05-22",
            "lines": [
                {"quantity": 84, "item_code": "EW9208", "description": "TT 50cl"},
            ],
        },
    }
    subject, body = auto_reply.build_confirmation(row)
    assert subject == "Re: Fwd: Bestelling X"
    assert "Park Inn Leuven" in body
    assert "PO-99" in body
    assert "2026-05-22" in body
    assert "ABC-123" in body
    assert "84" in body
    assert "EW9208" in body


def test_send_confirmation_threadt_op_message_id():
    sent = {}

    def sender(msg):
        sent["msg"] = msg

    row = {
        "id": "r1",
        "from_address": "Patrick <patrick@earthwater.nl>",
        "subject": "Fwd: X",
        "message_id": "<abc@x.nl>",
        "exact_order_id": "NR1",
        "parsed_data": {"matched_customer": {"name": "Y"}, "lines": []},
    }
    ok = auto_reply.send_confirmation(row, smtp_sender=sender)
    assert ok is True
    assert sent["msg"]["In-Reply-To"] == "<abc@x.nl>"
    assert sent["msg"]["References"] == "<abc@x.nl>"
    assert sent["msg"]["Subject"].startswith("Re:")


def test_maybe_send_confirmation_alleen_bij_created_en_forwarder():
    sb = MagicMock()

    # Scenario 1: al verstuurd -> skip
    row = {"id": "r1", "from_address": "patrick@earthwater.nl",
           "exact_order_id": "X", "confirmation_sent_at": "2026-04-21T10:00:00Z",
           "parsed_data": {}}
    res = auto_reply.maybe_send_confirmation(row, sb, smtp_sender=lambda m: None)
    assert res["skipped_already_sent"] is True

    # Scenario 2: niet forwarder -> skip
    row = {"id": "r2", "from_address": "iemand@klant.nl",
           "exact_order_id": "X", "confirmation_sent_at": None, "parsed_data": {}}
    res = auto_reply.maybe_send_confirmation(row, sb, smtp_sender=lambda m: None)
    assert res["skipped_not_forwarder"] is True

    # Scenario 3: verkeerde parse_status -> skip
    row = {"id": "r3", "from_address": "patrick@earthwater.nl",
           "parse_status": "needs_review", "exact_order_id": None,
           "confirmation_sent_at": None, "parsed_data": {}}
    res = auto_reply.maybe_send_confirmation(row, sb, smtp_sender=lambda m: None)
    assert res["skipped_wrong_status"] is True

    # Scenario 4: alles OK -> wordt verstuurd en Supabase wordt geüpdatet
    captured = {}
    row = {
        "id": "r4",
        "from_address": "Patrick <patrick@earthwater.nl>",
        "subject": "Fwd: X",
        "message_id": "<a@b>",
        "parse_status": "created",
        "exact_order_id": "NR1",
        "confirmation_sent_at": None,
        "parsed_data": {"matched_customer": {"name": "K"}, "lines": []},
    }
    res = auto_reply.maybe_send_confirmation(
        row, sb, smtp_sender=lambda m: captured.setdefault("msg", m)
    )
    assert res["sent"] is True
    assert "msg" in captured
