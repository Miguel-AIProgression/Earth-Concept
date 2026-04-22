"""Tests voor mail_intake module."""

from email.message import EmailMessage
from unittest.mock import MagicMock, patch

import pytest

import mail_intake


def _build_raw_email(subject="Bestelling 123", from_addr="klant@voorbeeld.nl",
                     message_id="<abc@voorbeeld.nl>", body="Hallo, bestel 10 dozen",
                     attachment=None, in_reply_to=None, references=None):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = "orders@earthwater.nl"
    msg["Date"] = "Mon, 13 Apr 2026 10:00:00 +0000"
    if message_id is not None:
        msg["Message-ID"] = message_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    msg.set_content(body)
    if attachment:
        filename, ct, data = attachment
        maintype, subtype = ct.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return msg.as_bytes()


# ---------- RFC 5322 thread-detectie ----------


def test_parse_raw_extraheert_in_reply_to_en_references():
    raw = _build_raw_email(
        message_id="<child@earthwater.nl>",
        in_reply_to="<parent@earthwater.nl>",
        references="<grandparent@earthwater.nl> <parent@earthwater.nl>",
    )
    parsed = mail_intake._parse_raw(raw)
    assert parsed["message_id"] == "<child@earthwater.nl>"
    assert "<parent@earthwater.nl>" in parsed["references"]
    assert "<grandparent@earthwater.nl>" in parsed["references"]


def test_resolve_thread_id_zonder_references_is_root():
    sb = MagicMock()
    tid = mail_intake.resolve_thread_id(sb, "<root@x>", [])
    assert tid == "<root@x>"


def test_resolve_thread_id_erft_van_bekende_parent():
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"thread_id": "<root@x>", "message_id": "<parent@x>"}
    ]
    tid = mail_intake.resolve_thread_id(sb, "<child@x>", ["<parent@x>"])
    assert tid == "<root@x>"


def test_resolve_thread_id_pakt_eerste_bekende_ref():
    """Eerste reference die in DB staat, levert de thread_id."""
    sb = MagicMock()
    responses = [
        # Eerste lookup: onbekende reference → geen data
        MagicMock(data=[]),
        # Tweede lookup: bekende parent → levert thread-root
        MagicMock(data=[{"thread_id": "<root@x>", "message_id": "<parent@x>"}]),
    ]
    sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.side_effect = responses
    tid = mail_intake.resolve_thread_id(
        sb, "<child@x>", ["<onbekend@x>", "<parent@x>"]
    )
    assert tid == "<root@x>"


def test_resolve_thread_id_parent_zonder_thread_id_valt_terug_op_message_id():
    """Oude rijen uit backfill kunnen thread_id=NULL hebben; pak message_id."""
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"thread_id": None, "message_id": "<legacy-parent@x>"}
    ]
    tid = mail_intake.resolve_thread_id(sb, "<child@x>", ["<legacy-parent@x>"])
    assert tid == "<legacy-parent@x>"


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


def test_pdf_zonder_filename_wordt_alsnog_gepakt():
    """Outlook-forwards sturen een PDF soms aan als application/pdf zonder
    filename-parameter. Zonder fallback miste de pipeline de hele order."""
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["Subject"] = "RE:"
    msg["From"] = "michael@bblco.ie"
    msg["To"] = "orders@earthwater.nl"
    msg["Message-ID"] = "<x@y>"
    msg["Date"] = "Mon, 22 Apr 2026 11:26:00 +0000"
    msg.set_content("Hi, zie bijlage.")
    # Bewust zonder filename toevoegen:
    msg.add_attachment(b"%PDF-1.4 echte-order", maintype="application", subtype="pdf")
    # Strip de filename parameter alsnog (add_attachment zet 'm niet zonder, maar
    # voor de echtheid: simuleer door het Content-Disposition te overschrijven).
    for part in msg.iter_attachments():
        if "Content-Disposition" in part:
            del part["Content-Disposition"]

    parsed = mail_intake._parse_raw(msg.as_bytes())
    pdfs = [a for a in parsed["attachments"] if a["content_type"] == "application/pdf"]
    assert len(pdfs) == 1
    assert pdfs[0]["data"].startswith(b"%PDF-")


def test_pdf_als_octet_stream_met_pdf_magic_wordt_gepakt():
    """Sommige mailclients labelen PDFs als application/octet-stream."""
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["Subject"] = "Order"
    msg["From"] = "klant@x.nl"
    msg["To"] = "orders@earthwater.nl"
    msg["Message-ID"] = "<oct@y>"
    msg["Date"] = "Mon, 22 Apr 2026 11:26:00 +0000"
    msg.set_content("Bestelling bijgevoegd.")
    msg.add_attachment(
        b"%PDF-1.7 binary",
        maintype="application",
        subtype="octet-stream",
        filename="inkooporder",
    )

    parsed = mail_intake._parse_raw(msg.as_bytes())
    pdfs = [a for a in parsed["attachments"] if a["data"].startswith(b"%PDF-")]
    assert len(pdfs) == 1
    assert pdfs[0]["content_type"] == "application/pdf"
    assert pdfs[0]["filename"].lower().endswith(".pdf")


def test_pdf_in_geneste_rfc822_wordt_gepakt():
    """Bij Outlook-forwards zit de PDF vaak als bijlage ván het originele
    bericht dat message/rfc822-gewrapped is. walk() van de buitenste
    Message stapt daar niet automatisch in."""
    from email.message import EmailMessage

    # Origineel bericht mét PDF-bijlage
    inner = EmailMessage()
    inner["Subject"] = "Original PO"
    inner["From"] = "klant@x.nl"
    inner["To"] = "sales@earthwater.nl"
    inner["Message-ID"] = "<inner@x>"
    inner["Date"] = "Mon, 22 Apr 2026 09:00:00 +0000"
    inner.set_content("Hierbij onze PO.")
    inner.add_attachment(
        b"%PDF-1.5 nested-order",
        maintype="application",
        subtype="pdf",
        filename="PO-123.pdf",
    )

    # Forwarded wrapper
    outer = EmailMessage()
    outer["Subject"] = "Fwd: Original PO"
    outer["From"] = "patrick@earthwater.nl"
    outer["To"] = "orders@earthwater.nl"
    outer["Message-ID"] = "<outer@y>"
    outer["Date"] = "Mon, 22 Apr 2026 09:05:00 +0000"
    outer.set_content("Doorsturen naar intake.")
    # EmailMessage.add_attachment() voor message/rfc822 leidt content-type
    # zelf af uit het meegegeven Message-object, geen maintype/subtype.
    outer.add_attachment(inner)

    parsed = mail_intake._parse_raw(outer.as_bytes())
    pdfs = [a for a in parsed["attachments"] if a["content_type"] == "application/pdf"]
    assert len(pdfs) == 1
    assert pdfs[0]["data"].startswith(b"%PDF-")
    assert "PO-123" in pdfs[0]["filename"]


def test_signature_png_blijft_maar_pdf_wordt_ook_gepakt():
    """image001.png-handtekening moet niet de PDF verdringen."""
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["Subject"] = "RE:"
    msg["From"] = "michael@bblco.ie"
    msg["To"] = "orders@earthwater.nl"
    msg["Message-ID"] = "<sig@y>"
    msg["Date"] = "Mon, 22 Apr 2026 11:26:00 +0000"
    msg.set_content("Zie bijlage.")
    msg.add_attachment(
        b"\x89PNG\r\n\x1a\n" + b"x" * 100,
        maintype="image",
        subtype="png",
        filename="image001.png",
    )
    msg.add_attachment(
        b"%PDF-1.4 order",
        maintype="application",
        subtype="pdf",
        filename="order.pdf",
    )

    parsed = mail_intake._parse_raw(msg.as_bytes())
    types = {a["content_type"] for a in parsed["attachments"]}
    assert "application/pdf" in types
    assert "image/png" in types


def test_geen_message_id_gebruikt_hash():
    raw = _build_raw_email(message_id=None)
    parsed = mail_intake._parse_raw(raw)
    mid = parsed["message_id"]
    assert len(mid) == 64
    assert all(c in "0123456789abcdef" for c in mid)


def test_fetch_gebruikt_since_niet_unseen():
    """Regressie: UNSEEN sloeg mails over die Patrick al in Gmail had geopend."""
    imap = MagicMock()
    imap.search.return_value = ("OK", [b""])
    mail_intake.fetch_recent_messages(imap, lookback_days=7)
    assert imap.search.called
    args = imap.search.call_args.args
    assert "UNSEEN" not in args
    assert "SINCE" in args


def test_reeds_geopende_mail_wordt_alsnog_opgehaald():
    """Mails met Seen-flag moeten via SINCE nog steeds door de intake komen."""
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []

    imap = MagicMock()
    raw = _build_raw_email(message_id="<reeds-gelezen@voorbeeld.nl>")
    imap.search.return_value = ("OK", [b"42"])
    imap.fetch.return_value = ("OK", [(b"42 (BODY[] {x}", raw)])

    with patch.object(mail_intake, "save_message", return_value={"id": "new-id"}) as save_mock, \
         patch.object(mail_intake, "upload_attachments", return_value=[]), \
         patch.object(mail_intake, "mark_as_read"):
        stats = mail_intake.process_inbox(sb=sb, imap=imap, mark_read=True)

    assert save_mock.call_count == 1
    assert stats["new"] == 1
