"""End-to-end pipeline: mail intake -> parse -> match -> POST naar Exact.

Werking:
1. Haal nieuwe mails uit Gmail (mail_intake.process_inbox).
2. Pak alle incoming_orders met parse_status == 'pending' of 'parsed'.
3. Parse met Claude (parse_incoming_order) -> parsed_data + status.
4. Match klant + items (prepare_order_for_review) -> status approved,
   ready_for_approval of needs_review. Bij confidence >= 0.85 en
   vertrouwde item-sources wordt de order direct op 'approved' gezet.
5. POST naar Exact voor 'approved' rijen, tenzij afzender in TEST_SENDERS.
   Test-mails blijven zichtbaar in het dashboard met status 'test_context'.

Parse_status stroom:
    pending -> parsed -> approved -> created                    (hoge confidence, auto)
    pending -> parsed -> approved -> test_context               (miguel@aiprogression.nl)
    pending -> parsed -> ready_for_approval -> approved -> ...  (handmatige goedkeuring)
    pending -> needs_review                                     (lage confidence / geen match)
    pending -> failed                                           (parse-error)
"""

from __future__ import annotations

import logging
import os
from typing import Any

from dotenv import load_dotenv

log = logging.getLogger(__name__)

TEST_SENDERS = {"miguel@aiprogression.nl"}

PDF_MIME_TYPES = {"application/pdf"}


def _normalize_payload_dates(payload: dict) -> dict:
    """Converteer legacy /Date(ms)/-velden naar ISO 8601 dat Exact accepteert.

    Payloads die eerder door het dashboard zijn opgeslagen bevatten nog
    het OData v2 response-formaat. Exact's POST-endpoint wijst dat af
    met een DeliveryDate-parse-error.
    """
    import re
    out = dict(payload)
    for key in ("DeliveryDate", "OrderDate"):
        v = out.get(key)
        if isinstance(v, str):
            m = re.match(r"^/Date\((-?\d+)\)/$", v)
            if m:
                from datetime import datetime, timezone
                ms = int(m.group(1))
                dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
                out[key] = dt.strftime("%Y-%m-%dT00:00:00")
    return out


def _strip_zero_unit_prices(payload: dict) -> dict:
    """Haal UnitPrice=0 weg op regels zodat Exact de default-prijs invult.

    Oudere payloads (vóór de prijs-fix) bevatten nog UnitPrice: 0;
    zonder strippen komt de order met 0,00 in Exact terecht.
    """
    lines = payload.get("SalesOrderLines")
    if not isinstance(lines, list):
        return payload
    cleaned = []
    for line in lines:
        if not isinstance(line, dict):
            cleaned.append(line)
            continue
        up = line.get("UnitPrice")
        if isinstance(up, (int, float)) and up <= 0:
            line = {k: v for k, v in line.items() if k != "UnitPrice"}
        cleaned.append(line)
    out = dict(payload)
    out["SalesOrderLines"] = cleaned
    return out


def _attach_first_pdf(sb, exact_client, row: dict, parsed_data: dict, exact_order_id, order_nr) -> None:
    """Probeer de eerste PDF-bijlage uit de mail aan de SalesOrder te koppelen.

    Faalt stil; de hoofdlogica (order in Exact) is al gelukt op dit punt.
    """
    from exact_documents import attach_pdf_to_salesorder

    attachments = row.get("attachments") or []
    pdf = None
    for att in attachments:
        if (att.get("content_type") or "").lower() in PDF_MIME_TYPES:
            pdf = att
            break
    if not pdf:
        return
    storage_path = pdf.get("storage_path")
    if not storage_path:
        return

    account_id = (parsed_data.get("matched_customer") or {}).get("id")
    if not account_id:
        log.warning("Geen account_id beschikbaar voor PDF-attach, skip")
        return

    try:
        pdf_bytes = sb.storage.from_("order-attachments").download(storage_path)
    except Exception as e:
        log.warning("PDF %s ophalen uit storage mislukt: %s", storage_path, e)
        return

    try:
        attach_pdf_to_salesorder(
            exact=exact_client,
            account_id=account_id,
            salesorder_id=exact_order_id,
            salesorder_number=order_nr,
            filename=pdf.get("filename") or "order.pdf",
            pdf_bytes=pdf_bytes,
        )
    except Exception as e:
        log.warning("PDF-attach aan SalesOrder mislukt: %s", e)


def is_test_sender(from_address: str | None) -> bool:
    if not from_address:
        return False
    low = from_address.lower()
    return any(s in low for s in TEST_SENDERS)


def process_pending(sb, exact_client=None, anthropic_client=None) -> dict:
    """Verwerk alle incoming_orders die nog geen eindstatus hebben."""
    from order_parser import parse_incoming_order
    from order_creator import prepare_order_for_review

    stats = {
        "parsed": 0,
        "matched": 0,
        "posted": 0,
        "test_context": 0,
        "failed": 0,
        "skipped": 0,
        "auto_replies": 0,
        "confirmations": 0,
    }

    unfinished_statuses = ["pending", "parsed", "approved"]
    res = (
        sb.table("incoming_orders")
        .select("*")
        .in_("parse_status", unfinished_statuses)
        .order("received_at", desc=False)
        .execute()
    )
    rows = res.data or []
    log.info("Pipeline: %d rijen om te verwerken", len(rows))

    for row in rows:
        row_id = row.get("id")
        from_addr = row.get("from_address")
        status = row.get("parse_status")

        # Stap 1: parsing (als nog pending)
        if status == "pending":
            try:
                row = parse_incoming_order(row, sb, client=anthropic_client)
                status = row.get("parse_status")
                if status == "parsed":
                    stats["parsed"] += 1
                elif status == "failed":
                    stats["failed"] += 1
                    continue
                elif status == "needs_review":
                    continue
            except Exception as e:
                log.exception("Parse mislukt voor %s: %s", row_id, e)
                sb.table("incoming_orders").update(
                    {"parse_status": "failed", "error": f"parse error: {e}"}
                ).eq("id", row_id).execute()
                stats["failed"] += 1
                continue

        # Stap 2: matching + payload bouwen
        if status == "parsed" and exact_client is not None:
            try:
                row = prepare_order_for_review(row, exact_client, sb)
                status = row.get("parse_status")
                if status == "ready_for_approval":
                    stats["matched"] += 1
                else:
                    continue
            except Exception as e:
                log.exception("Matching mislukt voor %s: %s", row_id, e)
                sb.table("incoming_orders").update(
                    {"parse_status": "failed", "error": f"match error: {e}"}
                ).eq("id", row_id).execute()
                stats["failed"] += 1
                continue

        # Stap 3: POST naar Exact.
        # Alleen 'approved' rijen gaan door -- of ze nu auto-approved zijn
        # door prepare_order_for_review (confidence >= 0.85) of handmatig
        # goedgekeurd in het dashboard. 'ready_for_approval' blijft wachten.
        if status != "approved":
            continue

        if is_test_sender(from_addr):
            log.info("Testafzender %s -> blijft in dashboard zonder POST", from_addr)
            sb.table("incoming_orders").update(
                {"parse_status": "test_context"}
            ).eq("id", row_id).execute()
            stats["test_context"] += 1
            continue

        if exact_client is None:
            stats["skipped"] += 1
            continue

        try:
            parsed_data = row.get("parsed_data") or {}
            payload = parsed_data.get("salesorder_payload")
            if not payload:
                raise ValueError("Geen salesorder_payload in parsed_data")
            payload = _normalize_payload_dates(payload)
            payload = _strip_zero_unit_prices(payload)

            # Zet het afleveradres uit de PDF/mail om naar een Address-GUID,
            # anders pakt Exact het default-adres van de Account (dat kan
            # "NIET GEBRUIKEN"-records of verouderde adressen zijn).
            if "DeliveryAddress" not in payload:
                from exact_addresses import ensure_delivery_address_id

                addr_id = ensure_delivery_address_id(
                    exact_client,
                    payload.get("OrderedBy"),
                    parsed_data.get("delivery_address"),
                )
                if addr_id:
                    payload["DeliveryAddress"] = addr_id

            resp = exact_client.post("/salesorder/SalesOrders", payload)
            exact_id = resp.get("ID") if isinstance(resp, dict) else None
            order_nr = resp.get("OrderNumber") if isinstance(resp, dict) else None
            sb.table("incoming_orders").update(
                {
                    "parse_status": "created",
                    "exact_order_id": exact_id,
                    "error": None,
                }
            ).eq("id", row_id).execute()
            log.info("Order %s aangemaakt in Exact (nr %s)", row_id, order_nr)
            stats["posted"] += 1

            # Attach de eerste PDF-bijlage van de mail aan de SalesOrder.
            _attach_first_pdf(sb, exact_client, row, parsed_data, exact_id, order_nr)
        except Exception as e:
            log.exception("POST naar Exact mislukt voor %s: %s", row_id, e)
            sb.table("incoming_orders").update(
                {"parse_status": "failed", "error": f"post error: {e}"}
            ).eq("id", row_id).execute()
            stats["failed"] += 1

    # Stap 4: auto-reply naar de forward-afzender voor rijen die niet
    # automatisch konden worden verwerkt (parse_failed, no_lines,
    # customer_unknown, items_unmatched). Max één reply per order via
    # auto_reply_sent_at. Ook rijen die al eerder op failed/needs_review
    # staan uit vorige runs worden meegenomen.
    try:
        from auto_reply import maybe_send_auto_reply

        reply_targets = (
            sb.table("incoming_orders")
            .select("*")
            .in_("parse_status", ["failed", "needs_review"])
            .is_("auto_reply_sent_at", "null")
            .execute()
        )
        for r in reply_targets.data or []:
            try:
                res = maybe_send_auto_reply(r, sb)
                if res.get("sent"):
                    stats["auto_replies"] += 1
            except Exception as e:
                log.exception("Auto-reply faalde voor %s: %s", r.get("id"), e)
    except Exception as e:
        log.exception("Auto-reply stap overgeslagen: %s", e)

    # Stap 5: bevestigingsmail voor orders die succesvol in Exact zijn
    # aangemaakt (parse_status='created') en waarvoor nog geen bevestiging
    # is verstuurd. Alleen naar de forward-afzender (Patrick).
    try:
        from auto_reply import maybe_send_confirmation

        confirm_targets = (
            sb.table("incoming_orders")
            .select("*")
            .eq("parse_status", "created")
            .is_("confirmation_sent_at", "null")
            .execute()
        )
        for r in confirm_targets.data or []:
            try:
                res = maybe_send_confirmation(r, sb)
                if res.get("sent"):
                    stats["confirmations"] += 1
            except Exception as e:
                log.exception("Confirmation faalde voor %s: %s", r.get("id"), e)
    except Exception as e:
        log.exception("Confirmation stap overgeslagen: %s", e)

    log.info("Pipeline klaar: %s", stats)
    return stats


def run() -> dict:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

    from supabase import create_client
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

    from exact_client import ExactClient
    exact_client = ExactClient()

    # Stap 1: mails ophalen. Fouten hier mogen stap 2 niet blokkeren;
    # anders blijven goedgekeurde orders hangen als IMAP tijdelijk hapert.
    intake_stats: dict[str, Any] = {}
    try:
        from mail_intake import process_inbox
        intake_stats = process_inbox(sb=sb)
        log.info("Mail intake: %s", intake_stats)
    except Exception as e:
        log.exception("Mail intake faalde, ga door met pipeline: %s", e)
        intake_stats = {"error": str(e)}

    # Stap 2: verwerken (inclusief POST naar Exact voor 'approved' rijen).
    pipeline_stats = process_pending(sb, exact_client=exact_client)

    return {"intake": intake_stats, "pipeline": pipeline_stats}


if __name__ == "__main__":
    stats = run()
    print(stats)
