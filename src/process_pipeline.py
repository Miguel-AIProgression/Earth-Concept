"""End-to-end pipeline: mail intake -> parse -> match -> POST naar Exact.

Werking:
1. Haal nieuwe mails uit Gmail (mail_intake.process_inbox).
2. Pak alle incoming_orders met parse_status == 'pending' of 'parsed'.
3. Parse met Claude (parse_incoming_order) -> parsed_data + status.
4. Match klant + items (prepare_order_for_review) -> status ready_for_approval of needs_review.
5. POST naar Exact voor 'ready_for_approval' rijen, tenzij afzender in TEST_SENDERS.
   Test-mails blijven zichtbaar in het dashboard met status 'test_context'.

Parse_status stroom:
    pending -> parsed -> ready_for_approval -> created          (productie-mails)
    pending -> parsed -> ready_for_approval -> test_context     (miguel@aiprogression.nl)
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


def is_test_sender(from_address: str | None) -> bool:
    if not from_address:
        return False
    low = from_address.lower()
    return any(s in low for s in TEST_SENDERS)


def process_pending(sb, exact_client=None, anthropic_client=None) -> dict:
    """Verwerk alle incoming_orders die nog geen eindstatus hebben."""
    from order_parser import parse_incoming_order
    from order_creator import prepare_order_for_review

    stats = {"parsed": 0, "matched": 0, "posted": 0, "test_context": 0, "failed": 0, "skipped": 0}

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

        # Stap 3: POST naar Exact -- behalve voor testafzenders
        if status in ("ready_for_approval", "approved"):
            if status == "ready_for_approval" and is_test_sender(from_addr):
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
                payload = (row.get("parsed_data") or {}).get("salesorder_payload")
                if not payload:
                    raise ValueError("Geen salesorder_payload in parsed_data")
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
            except Exception as e:
                log.exception("POST naar Exact mislukt voor %s: %s", row_id, e)
                sb.table("incoming_orders").update(
                    {"parse_status": "failed", "error": f"post error: {e}"}
                ).eq("id", row_id).execute()
                stats["failed"] += 1

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

    # Stap 1: mails ophalen
    from mail_intake import process_inbox
    intake_stats = process_inbox(sb=sb)
    log.info("Mail intake: %s", intake_stats)

    # Stap 2: verwerken
    pipeline_stats = process_pending(sb, exact_client=exact_client)

    return {"intake": intake_stats, "pipeline": pipeline_stats}


if __name__ == "__main__":
    stats = run()
    print(stats)
