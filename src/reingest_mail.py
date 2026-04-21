"""Haal één specifieke mail opnieuw uit IMAP en overschrijf de Supabase-rij.

Gebruik: wanneer een bestaande incoming_orders-rij met oude/lege metadata
opnieuw door de intake moet (bijvoorbeeld nadat _extract_attachments is
bijgewerkt om inline-PDF's mee te nemen). Vindt de mail op Message-ID,
overschrijft body + attachments + zet parse_status terug op 'pending'.

    python reingest_mail.py <row-id>
"""

from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv

from mail_intake import (
    BUCKET,
    _parse_raw,
    connect_imap,
    upload_attachments,
)

log = logging.getLogger(__name__)


def _imap_search_by_message_id(imap, message_id: str) -> bytes | None:
    status, data = imap.search(None, "HEADER", "Message-ID", message_id)
    if status != "OK" or not data or not data[0]:
        return None
    ids = data[0].split()
    return ids[-1] if ids else None


def reingest(row_id: str) -> dict:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

    from supabase import create_client
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

    res = sb.table("incoming_orders").select("id,message_id").eq("id", row_id).limit(1).execute()
    if not res.data:
        raise SystemExit(f"Rij {row_id} niet gevonden")
    message_id = res.data[0]["message_id"]
    log.info("Rij %s -> Message-ID %s", row_id, message_id)

    imap = connect_imap()
    try:
        uid = _imap_search_by_message_id(imap, message_id)
        if not uid:
            raise SystemExit(f"Mail met Message-ID {message_id} niet gevonden in INBOX")
        log.info("Gevonden op UID %s", uid.decode())

        status, msg_data = imap.fetch(uid, "(RFC822)")
        if status != "OK":
            raise SystemExit(f"IMAP fetch faalde voor UID {uid}")

        raw = None
        for item in msg_data:
            if isinstance(item, tuple) and len(item) >= 2:
                raw = item[1]
                break
        if not raw:
            raise SystemExit("Geen raw bytes van IMAP")

        parsed = _parse_raw(raw)
    finally:
        try:
            imap.close()
            imap.logout()
        except Exception:
            pass

    # Verwijder oude storage-objecten voor deze message_id (best-effort).
    try:
        existing = sb.storage.from_(BUCKET).list(parsed["message_id"])
        if existing:
            paths = [f"{parsed['message_id']}/{f['name']}" for f in existing if f.get("name")]
            if paths:
                sb.storage.from_(BUCKET).remove(paths)
                log.info("Oude bijlages verwijderd: %d", len(paths))
    except Exception as e:
        log.warning("Kon oude bijlages niet wissen: %s", e)

    meta = upload_attachments(sb, parsed["message_id"], parsed.get("attachments") or [])
    log.info("Bijlagen geüpload: %d", len(meta))

    update = {
        "received_at": parsed.get("received_at") or None,
        "from_address": parsed.get("from_address"),
        "subject": parsed.get("subject"),
        "body_text": parsed.get("body_text"),
        "body_html": parsed.get("body_html"),
        "attachments": meta,
        "parse_status": "pending",
        "parsed_data": None,
        "exact_order_id": None,
        "error": None,
        "auto_reply_sent_at": None,
        "confirmation_sent_at": None,
    }
    sb.table("incoming_orders").update(update).eq("id", row_id).execute()
    log.info("Rij %s bijgewerkt, status=pending, bijlages=%d", row_id, len(meta))

    return {"row_id": row_id, "attachments": len(meta)}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: python reingest_mail.py <row-id>")
    stats = reingest(sys.argv[1])
    print(stats)
