"""Dump de MIME-structuur van één mail uit IMAP voor debugging.

Gebruik: wanneer een intake-rij geen PDF oppikt terwijl de afzender
beweert er wel een te hebben meegestuurd. Toont álle parts (ook nested
rfc822) met Content-Type, filename, grootte en eerste bytes, plus de
eerste 2 KB van body_text/body_html zodat we externe links (Google
Drive, OneDrive, WeTransfer) kunnen spotten.

    python debug_mail.py <row-id>
"""

from __future__ import annotations

import os
import re
import sys

from dotenv import load_dotenv

from mail_intake import connect_imap


def _short(raw: bytes, n: int = 120) -> str:
    try:
        s = raw.decode("utf-8", errors="replace")
    except Exception:
        s = repr(raw[:n])
    s = s.replace("\r", "\\r").replace("\n", "\\n")
    return s[:n]


def _walk_and_print(msg, indent: int = 0) -> None:
    prefix = "  " * indent
    ct = msg.get_content_type()
    disp = msg.get_content_disposition()
    filename = msg.get_filename()
    try:
        payload = msg.get_payload(decode=True)
    except Exception:
        payload = None

    size = len(payload) if isinstance(payload, bytes) else "n/a"
    print(f"{prefix}- {ct} disp={disp} filename={filename!r} size={size}")
    if isinstance(payload, bytes) and payload:
        head = payload[:8]
        is_pdf = payload[:5] == b"%PDF-"
        print(f"{prefix}    head_bytes={head!r} is_pdf={is_pdf}")

    if ct == "message/rfc822":
        sub = msg.get_payload()
        if isinstance(sub, list) and sub:
            print(f"{prefix}  -- nested rfc822 --")
            _walk_and_print(sub[0], indent + 2)
    elif msg.is_multipart():
        for sub in msg.get_payload():
            _walk_and_print(sub, indent + 1)


def _find_urls(text: str) -> list[str]:
    if not text:
        return []
    urls = re.findall(r"https?://[^\s<>\"')]+", text)
    interesting = [
        u for u in urls
        if any(k in u.lower() for k in ("drive.google", "onedrive", "sharepoint",
                                        "wetransfer", "dropbox", "box.com",
                                        ".pdf"))
    ]
    return interesting[:20]


def debug(row_id: str) -> None:
    load_dotenv()
    from supabase import create_client
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

    res = (
        sb.table("incoming_orders")
        .select("id,message_id,subject,from_address,body_text,body_html")
        .eq("id", row_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise SystemExit(f"Rij {row_id} niet gevonden")
    row = res.data[0]
    message_id = row["message_id"]
    print(f"Row {row_id}")
    print(f"Message-ID: {message_id}")
    print(f"Subject: {row.get('subject')!r}")
    print(f"From: {row.get('from_address')!r}")
    print()

    imap = connect_imap()
    try:
        status, data = imap.search(None, "HEADER", "Message-ID", message_id)
        if status != "OK" or not data or not data[0]:
            raise SystemExit(f"Mail {message_id} niet gevonden in INBOX")
        uid = data[0].split()[-1]
        status, msg_data = imap.fetch(uid, "(RFC822)")
        raw = None
        for item in msg_data:
            if isinstance(item, tuple) and len(item) >= 2:
                raw = item[1]
                break
        if not raw:
            raise SystemExit("Geen raw bytes")
        print(f"RFC822 grootte: {len(raw)} bytes")
        print()

        import email
        msg = email.message_from_bytes(raw)
        print("MIME-structuur:")
        _walk_and_print(msg)
        print()
    finally:
        try:
            imap.close()
            imap.logout()
        except Exception:
            pass

    print("Body-tekst (eerste 2 KB):")
    print(_short(str(row.get("body_text") or "").encode("utf-8"), 2048))
    print()
    print("Body-HTML (eerste 2 KB):")
    print(_short(str(row.get("body_html") or "").encode("utf-8"), 2048))
    print()
    interesting = _find_urls((row.get("body_text") or "") + "\n" + (row.get("body_html") or ""))
    print("Verdachte download-URLs in body:")
    for u in interesting:
        print(f"  - {u}")
    if not interesting:
        print("  (geen cloud-storage/PDF-URLs gevonden)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: python debug_mail.py <row-id>")
    debug(sys.argv[1])
