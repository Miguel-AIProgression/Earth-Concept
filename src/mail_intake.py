"""Gmail IMAP intake -> Supabase `incoming_orders`.

Poller die de orders@earthwater.nl mailbox uitleest via IMAP (app-password),
nieuwe mails opslaat in Supabase en bijlagen uploadt naar storage bucket
`order-attachments`. Parsing van de order-inhoud gebeurt in een latere stap.

We filteren op SINCE (laatste N dagen), niet op UNSEEN: anders komen mails
die Patrick al in Gmail heeft geopend nooit in het portaal. Dedup gebeurt
op Message-ID via `message_already_seen()`.
"""

from __future__ import annotations

import email
import hashlib
import imaplib
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

from dotenv import load_dotenv

log = logging.getLogger(__name__)

IMAP_HOST = os.getenv("MAIL_HOST", "imap.gmail.com")
IMAP_PORT = int(os.getenv("MAIL_PORT", "993"))
BUCKET = "order-attachments"
# Lookback-venster voor de IMAP SEARCH. We filteren bewust niet op UNSEEN,
# omdat mails die Patrick al in Gmail heeft geopend dan nooit in het portaal
# komen. Dedup gebeurt verderop via message_already_seen().
DEFAULT_LOOKBACK_DAYS = int(os.getenv("MAIL_LOOKBACK_DAYS", "14"))


def connect_imap() -> imaplib.IMAP4_SSL:
    user = os.environ["MAIL_USER"]
    password = os.environ["MAIL_PASS"]
    imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    imap.login(user, password)
    imap.select("INBOX")
    return imap


def _decode_header(raw) -> str:
    if raw is None:
        return ""
    try:
        from email.header import decode_header, make_header
        return str(make_header(decode_header(raw)))
    except Exception:
        return str(raw)


def _extract_body(msg) -> tuple[str, str]:
    text_body = ""
    html_body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                continue
            ct = part.get_content_type()
            if ct == "text/plain" and not text_body:
                charset = part.get_content_charset() or "utf-8"
                text_body = part.get_payload(decode=True).decode(charset, errors="replace")
            elif ct == "text/html" and not html_body:
                charset = part.get_content_charset() or "utf-8"
                html_body = part.get_payload(decode=True).decode(charset, errors="replace")
    else:
        charset = msg.get_content_charset() or "utf-8"
        payload = msg.get_payload(decode=True)
        if payload is not None:
            body = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                html_body = body
            else:
                text_body = body
    return text_body, html_body


def _extract_attachments(msg) -> list[dict]:
    attachments = []
    if not msg.is_multipart():
        return attachments
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        filename = part.get_filename()
        if not filename:
            continue
        disp = part.get_content_disposition()
        if disp not in ("attachment", "inline"):
            continue
        data = part.get_payload(decode=True) or b""
        attachments.append({
            "filename": _decode_header(filename),
            "content_type": part.get_content_type(),
            "data": data,
        })
    return attachments


def _parse_raw(raw: bytes) -> dict:
    msg = email.message_from_bytes(raw)
    message_id = (msg.get("Message-ID") or "").strip()
    if not message_id:
        message_id = hashlib.sha256(raw).hexdigest()

    date_hdr = msg.get("Date")
    if date_hdr:
        try:
            received_at = parsedate_to_datetime(date_hdr).isoformat()
        except Exception:
            received_at = ""
    else:
        received_at = ""

    text_body, html_body = _extract_body(msg)

    return {
        "message_id": message_id,
        "received_at": received_at,
        "from_address": _decode_header(msg.get("From")),
        "subject": _decode_header(msg.get("Subject")),
        "body_text": text_body,
        "body_html": html_body,
        "attachments": _extract_attachments(msg),
    }


def fetch_recent_messages(
    imap: imaplib.IMAP4_SSL, lookback_days: int | None = None
) -> list[dict]:
    """Haal mails op uit de laatste N dagen, ongeacht Seen-flag.

    We gebruiken SINCE in plaats van UNSEEN omdat Patrick mails soms
    al in Gmail opent voordat de pipeline ze ophaalt; UNSEEN zou die
    dan voorgoed overslaan. Dedup loopt via message_already_seen().
    BODY.PEEK[] laat het Seen-vlag ongemoeid tijdens het ophalen.
    """
    days = lookback_days if lookback_days is not None else DEFAULT_LOOKBACK_DAYS
    since_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%d-%b-%Y")
    status, data = imap.search(None, "SINCE", since_date)
    if status != "OK" or not data or not data[0]:
        return []
    ids = data[0].split()
    messages = []
    for num in ids:
        status, msg_data = imap.fetch(num, "(BODY.PEEK[])")
        if status != "OK" or not msg_data:
            continue
        raw = None
        for item in msg_data:
            if isinstance(item, tuple) and len(item) >= 2:
                raw = item[1]
                break
        if not raw:
            continue
        parsed = _parse_raw(raw)
        parsed["_imap_uid"] = num
        messages.append(parsed)
    return messages


def message_already_seen(sb, message_id: str) -> bool:
    res = sb.table("incoming_orders").select("id").eq("message_id", message_id).limit(1).execute()
    return bool(res.data)


_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_storage_segment(raw: str) -> str:
    """Supabase Storage accepteert geen <, >, @, spaties e.d. in paden."""
    return _SAFE_SEGMENT.sub("_", raw).strip("_.") or "unnamed"


def upload_attachments(sb, message_id: str, attachments: list[dict]) -> list[dict]:
    folder = _safe_storage_segment(message_id)
    uploaded = []
    for att in attachments:
        safe_name = _safe_storage_segment(att["filename"])
        path = f"{folder}/{safe_name}"
        try:
            sb.storage.from_(BUCKET).upload(
                path,
                att["data"],
                file_options={"content-type": att["content_type"]},
            )
        except Exception as e:
            log.warning("Upload bijlage mislukt (%s): %s", path, e)
        uploaded.append({
            "filename": att["filename"],
            "content_type": att["content_type"],
            "storage_path": path,
            "size": len(att["data"]),
        })
    return uploaded


def save_message(sb, msg: dict) -> dict:
    row = {
        "message_id": msg["message_id"],
        "received_at": msg["received_at"] or None,
        "from_address": msg.get("from_address"),
        "subject": msg.get("subject"),
        "body_text": msg.get("body_text"),
        "body_html": msg.get("body_html"),
        "attachments": msg.get("attachments_meta", []),
        "parse_status": "pending",
    }
    res = sb.table("incoming_orders").upsert(
        row, on_conflict="message_id", ignore_duplicates=True
    ).execute()
    return res.data[0] if res.data else row


def mark_as_read(imap: imaplib.IMAP4_SSL, uid) -> None:
    try:
        imap.store(uid, "+FLAGS", "\\Seen")
    except Exception as e:
        log.warning("Kon IMAP-flag niet zetten voor %s: %s", uid, e)


def process_inbox(sb=None, imap=None, mark_read: bool = True) -> dict:
    stats = {"fetched": 0, "new": 0, "skipped": 0, "errors": 0}

    close_imap = False
    if imap is None:
        imap = connect_imap()
        close_imap = True
    if sb is None:
        from supabase import create_client
        sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

    try:
        messages = fetch_recent_messages(imap)
        stats["fetched"] = len(messages)
        for msg in messages:
            try:
                if message_already_seen(sb, msg["message_id"]):
                    stats["skipped"] += 1
                    if mark_read:
                        mark_as_read(imap, msg.get("_imap_uid"))
                    continue
                meta = upload_attachments(sb, msg["message_id"], msg.get("attachments", []))
                msg["attachments_meta"] = meta
                save_message(sb, msg)
                if mark_read:
                    mark_as_read(imap, msg.get("_imap_uid"))
                stats["new"] += 1
            except Exception as e:
                log.exception("Fout bij verwerken mail %s: %s", msg.get("message_id"), e)
                stats["errors"] += 1
    finally:
        if close_imap:
            try:
                imap.close()
                imap.logout()
            except Exception:
                pass
    return stats


if __name__ == "__main__":
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    log.info("Mail intake starten (host=%s, user=%s)", IMAP_HOST, os.getenv("MAIL_USER"))
    stats = process_inbox()
    log.info("Intake klaar: %s", stats)
    print(stats)
