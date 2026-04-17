"""Koppel een PDF-bijlage aan een SalesOrder in Exact Online.

Exact heeft geen direct attachment-veld op SalesOrder; werkwijze:
  1. POST /documents/Documents (Type 10 = Algemeen) met Subject die het
     ordernummer bevat, gelinkt aan de Account en — indien het veld
     bestaat — aan de SalesOrder.
  2. POST /documents/DocumentAttachments met het Document-ID en de PDF
     als base64.

Bij fouten alleen loggen; we willen dat de hoofd-order niet ongedaan
wordt gemaakt als de bijlage-upload faalt.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

log = logging.getLogger(__name__)

# Exact Document types
DOCUMENT_TYPE_GENERAL = 10


def attach_pdf_to_salesorder(
    exact,
    account_id: str,
    salesorder_id: str | None,
    salesorder_number: int | str | None,
    filename: str,
    pdf_bytes: bytes,
    subject_prefix: str = "Order-PDF",
) -> dict[str, Any] | None:
    """Upload een PDF en koppel aan SalesOrder. Retourneert doc-dict of None."""
    if not pdf_bytes:
        return None

    short_nr = salesorder_number or (salesorder_id[:8] if salesorder_id else "?")
    subject = f"{subject_prefix} {short_nr}"

    doc_payload: dict[str, Any] = {
        "Subject": subject,
        "Type": DOCUMENT_TYPE_GENERAL,
        "Account": account_id,
    }
    if salesorder_id:
        # Exact accepteert stil als veld niet bestaat; wel proberen.
        doc_payload["SalesOrder"] = salesorder_id

    try:
        doc = exact.post("/documents/Documents", doc_payload)
    except Exception as e:
        # Fallback: als SalesOrder-veld de POST brak, nog eens zonder.
        log.warning("Document-aanmaak mislukt (%s); retry zonder SalesOrder-link", e)
        doc_payload.pop("SalesOrder", None)
        try:
            doc = exact.post("/documents/Documents", doc_payload)
        except Exception as e2:
            log.error("Document-aanmaak definitief mislukt: %s", e2)
            return None

    doc_id = doc.get("ID") if isinstance(doc, dict) else None
    if not doc_id:
        log.error("Document-respons zonder ID: %s", doc)
        return None

    try:
        exact.post(
            "/documents/DocumentAttachments",
            {
                "Document": doc_id,
                "Attachment": base64.b64encode(pdf_bytes).decode("ascii"),
                "FileName": filename,
            },
        )
    except Exception as e:
        log.error("DocumentAttachment mislukt voor doc %s: %s", doc_id, e)
        return {"document_id": doc_id, "attachment_uploaded": False}

    log.info("PDF %s geattacheerd aan Document %s (SO %s)", filename, doc_id, short_nr)
    return {"document_id": doc_id, "attachment_uploaded": True}
