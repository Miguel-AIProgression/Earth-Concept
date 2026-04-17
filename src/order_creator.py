"""Bouw een SalesOrder-payload voor Exact Online, incl. klant- en artikelmatching.

Matching gebeurt tegen een lokale Supabase-katalogus (nightly gesynced door
catalog_sync.py) met rapidfuzz en alias-leren — zie src/matcher.py.
Deze module doet GEEN live POST naar Exact; dat gebeurt in process_pipeline.

Mogelijke parse_status waarden in incoming_orders:
    pending | parsed | needs_review | ready_for_approval | approved | created | failed
"""

from __future__ import annotations

import calendar
import logging
from datetime import datetime
from typing import Any

import matcher

log = logging.getLogger(__name__)


def _date_to_odata(date_str: str) -> str:
    """YYYY-MM-DD -> /Date(ms)/ formaat zoals Exact verwacht."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    ms = calendar.timegm(dt.timetuple()) * 1000
    return f"/Date({ms})/"


def build_salesorder_payload(
    parsed: dict,
    account_id: str,
    matched_items: list[dict],
    description: str | None = None,
) -> dict:
    """Bouw JSON-body voor POST /salesorder/SalesOrders."""
    lines_payload = []
    for m in matched_items:
        if not m.get("item_id"):
            raise ValueError(
                f"Kan geen payload bouwen: item_id ontbreekt voor regel {m.get('line')}"
            )
        line = m["line"]
        lines_payload.append({
            "Item": m["item_id"],
            "Quantity": line.get("quantity", 0),
            "UnitPrice": line.get("unit_price", 0),
            "Description": line.get("description", ""),
        })

    payload: dict[str, Any] = {
        "OrderedBy": account_id,
        "YourRef": parsed.get("customer_reference", ""),
        "Description": description or parsed.get("description", ""),
        "SalesOrderLines": lines_payload,
    }

    delivery_date = parsed.get("delivery_date")
    if delivery_date:
        payload["DeliveryDate"] = _date_to_odata(delivery_date)

    return payload


def compute_overall_confidence(
    customer_match: dict | None, item_matches: list[dict]
) -> float:
    """Gewogen gemiddelde: customer 40%, items 60%.

    0.0 als customer ontbreekt of als een item_id None is.
    """
    if not customer_match:
        return 0.0
    if not item_matches:
        return 0.0
    if any(m.get("item_id") is None for m in item_matches):
        return 0.0

    cust_conf = float(customer_match.get("confidence", 0.0))
    item_conf = sum(float(m.get("confidence", 0.0)) for m in item_matches) / len(item_matches)
    return cust_conf * 0.4 + item_conf * 0.6


def prepare_order_for_review(incoming_row: dict, client, sb) -> dict:
    """Match klant + items via Supabase-katalogus, bouw payload, persist.

    ``client`` (ExactClient) is alleen nog nodig voor de uiteindelijke POST.
    """
    parsed = dict(incoming_row.get("parsed_data") or {})
    customer_name = parsed.get("customer_name") or parsed.get("customer") or ""
    lines = parsed.get("lines") or []

    customer_match = matcher.match_customer(sb, customer_name)
    item_matches = matcher.match_items(sb, lines)
    confidence = compute_overall_confidence(customer_match, item_matches)

    payload = None
    build_error = None
    if customer_match and all(m.get("item_id") for m in item_matches) and item_matches:
        try:
            payload = build_salesorder_payload(
                parsed,
                customer_match["id"],
                item_matches,
                description=parsed.get("description"),
            )
        except ValueError as e:
            build_error = str(e)
            log.warning("Payload build mislukt: %s", e)

    parsed["matched_customer"] = customer_match
    parsed["matched_items"] = item_matches
    parsed["salesorder_payload"] = payload
    parsed["match_confidence"] = confidence
    if build_error:
        parsed["match_error"] = build_error

    # Fuzzy item-matches zijn te riskant voor auto-gate: zelfs bij hoge
    # WRatio-score kan het product compleet verkeerd zijn (bv. Sparkling
    # vs. ANWB-TT). Vereis dat elk item via code of alias is gekoppeld.
    trusted_sources = {"code", "code-prefix", "alias"}
    all_items_trusted = bool(item_matches) and all(
        (m.get("source") in trusted_sources) for m in item_matches
    )

    if payload is not None and confidence >= 0.9 and all_items_trusted:
        new_status = "ready_for_approval"
    else:
        new_status = "needs_review"

    update = {
        "parsed_data": parsed,
        "parse_status": new_status,
    }

    try:
        sb.table("incoming_orders").update(update).eq("id", incoming_row["id"]).execute()
    except Exception as e:
        log.error("Kon incoming_orders rij niet updaten: %s", e)

    updated_row = dict(incoming_row)
    updated_row.update(update)
    return updated_row
