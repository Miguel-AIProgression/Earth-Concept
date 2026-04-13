"""Tests voor mail_intake module."""

from email.message import EmailMessage
from unittest.mock import MagicMock, patch

import pytest

import mail_intake


def _build_raw_email(subject="Bestelling 123", from_addr="klant@voorbeeld.nl",
                     message_id="<abc@voorbeeld.nl>", body="Hallo, bestel 10 dozen",
                     attachment=None):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = "orders@earthwater.nl"
    msg["Date"] = "Mon, 13 Apr 2026 10:00:00 +0000"
    if message_id is not None:
        msg["Message-ID"] = message_id
    msg.set_content(body)
    if attachment:
        filename, ct, data = attachment
        maintype, subtype = ct.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return msg.as_bytes()


def test_bekend_message_id_skippen():
    sb = MagicMock()
    # message_already_seen returnt True
    sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{"id": "x"}]

    imap = MagicMock()
    raw = _build_raw_email()
    imap.search.return_value = ("OK", [b"1"])
    imap.fetch.return_value = ("OK", [(b"1 (RFC822 {" + str(len(raw)).encode() + b"}", raw)])
    imap.uid.return_value = ("OK", [b"1"])

    with patch.object(mail_intake, "save_message") as save_mock, \
         patch.object(mail_intake, "upload_attachments") as upload_mock:
        stats = mail_intake.process_inbox(sb=sb, imap=imap, mark_read=False)

    assert save_mock.call_count == 0
    assert upload_mock.call_count == 0
    assert stats["skipped"] == 1
    assert stats["new"] == 0


def test_nieuw_bericht_opgeslagen():
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []

    imap = MagicMock()
    raw = _build_raw_email()
    imap.search.return_value = ("OK", [b"1"])
    imap.fetch.return_value = ("OK", [(b"1 (RFC822 {x}", raw)])

    with patch.object(mail_intake, "save_message", return_value={"id": "new-id"}) as save_mock, \
         patch.object(mail_intake, "upload_attachments", return_value=[]) as upload_mock, \
         patch.object(mail_intake, "mark_as_read") as mark_mock:
        stats = mail_intake.process_inbox(sb=sb, imap=imap, mark_read=True)

    assert save_mock.call_count == 1
    assert upload_mock.call_count == 1
    assert mark_mock.call_count == 1
    assert stats["new"] == 1


def test_parse_rfc822_headers():
    raw = _build_raw_email(subject="Test onderwerp", from_addr="a@b.nl",
                           message_id="<uniek-123@b.nl>", body="body hier")
    parsed = mail_intake._parse_raw(raw)
    assert parsed["message_id"] == "<uniek-123@b.nl>"
    assert parsed["subject"] == "Test onderwerp"
    assert "a@b.nl" in parsed["from_address"]
    assert "body hier" in parsed["body_text"]
    assert parsed["received_at"].startswith("2026-04-13")


def test_bijlage_geextraheerd():
    raw = _build_raw_email(attachment=("order.pdf", "application/pdf", b"%PDF-1.4 fakepdf"))
    parsed = mail_intake._parse_raw(raw)
    assert len(parsed["attachments"]) == 1
    att = parsed["attachments"][0]
    assert att["filename"] == "order.pdf"
    assert att["content_type"] == "application/pdf"
    assert att["data"] == b"%PDF-1.4 fakepdf"


def test_geen_message_id_gebruikt_hash():
    raw = _build_raw_email(message_id=None)
    parsed = mail_intake._parse_raw(raw)
    mid = parsed["message_id"]
    assert len(mid) == 64
    assert all(c in "0123456789abcdef" for c in mid)
