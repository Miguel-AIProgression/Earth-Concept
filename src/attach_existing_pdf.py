"""Retroactief: voor een reeds-gecreëerde SalesOrder de PDF-bijlage alsnog uploaden.

Gebruik:
    python attach_existing_pdf.py <incoming_order_id>

Stappen:
  1. Haal incoming_orders-rij op uit Supabase (attachments + matched_customer + customer_reference).
  2. Zoek de SalesOrder in Exact op YourRef of (fallback) op Account + recente datum.
  3. Update incoming_orders.exact_order_id als die nog leeg was.
  4. Koppel de PDF via exact_documents.attach_pdf_to_salesorder.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

log = logging.getLogger(__name__)


def _find_salesorder(exact, account_id: str, your_ref: str | None):
    """Zoek de meest recente matchende SalesOrder voor deze account."""
    if your_ref:
        your_ref_safe = your_ref.replace("'", "''")
        results = exact.get(
            "/salesorder/SalesOrders",
            params={
                "$filter": f"YourRef eq '{your_ref_safe}'",
                "$select": "OrderID,OrderNumber,YourRef,Created,OrderedBy",
                "$orderby": "Created desc",
            },
        ) or []
        for r in results:
            if r.get("OrderedBy") == account_id:
                return r
        if results:
            return results[0]

    # Fallback: recente orders voor deze account (laatste 24 uur).
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")
    results = exact.get(
        "/salesorder/SalesOrders",
        params={
            "$filter": f"OrderedBy eq guid'{account_id}' and Created gt datetime'{since}'",
            "$select": "OrderID,OrderNumber,YourRef,Created",
            "$orderby": "Created desc",
        },
    ) or []
    return results[0] if results else None


def run(row_id: str) -> dict:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

    from supabase import create_client
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

    res = sb.table("incoming_orders").select("*").eq("id", row_id).single().execute()
    row = res.data
    if not row:
        raise SystemExit(f"Rij {row_id} niet gevonden")

    parsed = row.get("parsed_data") or {}
    account_id = (parsed.get("matched_customer") or {}).get("id")
    your_ref = parsed.get("customer_reference")
    attachments = row.get("attachments") or []

    pdf = next((a for a in attachments if (a.get("content_type") or "").lower() == "application/pdf"), None)
    if not pdf:
        raise SystemExit("Geen PDF-bijlage in deze rij")
    if not account_id:
        raise SystemExit("Rij heeft geen matched_customer.id — kan niet zoeken")

    from exact_client import ExactClient
    exact = ExactClient()

    so = _find_salesorder(exact, account_id, your_ref)
    if not so:
        raise SystemExit(f"Kon geen SalesOrder vinden voor account {account_id} (YourRef={your_ref})")
    so_id = so.get("OrderID")
    so_nr = so.get("OrderNumber")
    log.info("Gevonden SalesOrder: ID=%s, OrderNumber=%s, YourRef=%s", so_id, so_nr, so.get("YourRef"))

    # Backfill exact_order_id in Supabase.
    if so_id and not row.get("exact_order_id"):
        sb.table("incoming_orders").update({"exact_order_id": so_id}).eq("id", row_id).execute()
        log.info("exact_order_id bijgewerkt naar %s", so_id)

    storage_path = pdf["storage_path"]
    pdf_bytes = sb.storage.from_("order-attachments").download(storage_path)
    log.info("PDF gedownload uit storage: %s (%d bytes)", storage_path, len(pdf_bytes))

    from exact_documents import attach_pdf_to_salesorder
    result = attach_pdf_to_salesorder(
        exact=exact,
        account_id=account_id,
        salesorder_id=so_id,
        salesorder_number=so_nr,
        filename=pdf.get("filename") or "order.pdf",
        pdf_bytes=pdf_bytes,
    )
    return {"row_id": row_id, "salesorder_id": so_id, "order_number": so_nr, "attach_result": result}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: python attach_existing_pdf.py <incoming_order_id>")
    out = run(sys.argv[1])
    print(out)
