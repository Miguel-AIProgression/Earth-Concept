"""Bouw een SalesOrder-payload voor Exact Online, incl. klant- en artikelmatching.

Deze module doet GEEN live POST naar Exact. Hij bereidt enkel het payload voor
en laat Patrick via het review-dashboard beslissen of de order verstuurd wordt.

Mogelijke parse_status waarden in incoming_orders:
    pending | parsed | needs_review | ready_for_approval | approved | created | failed

- pending:             mail ontvangen, nog niet geparsed
- parsed:              AI parser klaar, data beschikbaar
- needs_review:        handmatige controle nodig (lage confidence / missende data)
- ready_for_approval:  payload klaar, wacht op akkoord van Patrick
- approved:            Patrick heeft op 'verzenden' gedrukt (latere task)
- created:             POST naar Exact SalesOrders gelukt (latere task)
- failed:              parser/matcher error
"""

from __future__ import annotations

import calendar
import logging
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)


def _escape(value: str) -> str:
    """Escape single quotes voor OData $filter."""
    return value.replace("'", "''")


def match_customer(client, customer_name: str) -> dict | None:
    """Zoek Exact Account op basis van naam.

    1) Exact match op Name.
    2) Bij 0 of meerdere: fuzzy fallback via substringof.
    """
    if not customer_name:
        return None

    name_safe = _escape(customer_name)
    exact_results = client.get(
        "/crm/Accounts",
        params={
            "$filter": f"Name eq '{name_safe}'",
            "$select": "ID,Name,Code",
        },
    ) or []

    if len(exact_results) == 1:
        r = exact_results[0]
        return {"id": r.get("ID"), "name": r.get("Name"), "confidence": 1.0}

    if len(exact_results) > 1:
        r = exact_results[0]
        return {"id": r.get("ID"), "name": r.get("Name"), "confidence": 0.8}

    # Fuzzy fallback
    fuzzy_results = client.get(
        "/crm/Accounts",
        params={
            "$filter": f"substringof('{name_safe}', Name)",
            "$select": "ID,Name,Code",
        },
    ) or []

    if not fuzzy_results:
        return None

    best = min(fuzzy_results, key=lambda r: len(r.get("Name") or ""))
    return {"id": best.get("ID"), "name": best.get("Name"), "confidence": 0.7}


def match_items(client, lines: list[dict]) -> list[dict]:
    """Match order regels naar Exact Items via code of description."""
    results = []
    for line in lines:
        code = (line.get("item_code") or "").strip()
        description = (line.get("description") or "").strip()

        matched = {
            "line": line,
            "item_id": None,
            "item_code": None,
            "confidence": 0.0,
        }

        if code:
            code_safe = _escape(code)
            hits = client.get(
                "/logistics/Items",
                params={"$filter": f"Code eq '{code_safe}'", "$select": "ID,Code,Description"},
            ) or []
            if hits:
                h = hits[0]
                matched["item_id"] = h.get("ID")
                matched["item_code"] = h.get("Code")
                matched["confidence"] = 1.0
                results.append(matched)
                continue

        if description:
            words = description.split()[:3]
            snippet = " ".join(words)
            snippet_safe = _escape(snippet)
            hits = client.get(
                "/logistics/Items",
                params={
                    "$filter": f"substringof('{snippet_safe}', Description)",
                    "$select": "ID,Code,Description",
                },
            ) or []
            if hits:
                h = hits[0]
                matched["item_id"] = h.get("ID")
                matched["item_code"] = h.get("Code")
                matched["confidence"] = 0.6

        results.append(matched)
    return results


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
    """Match klant + items, bouw payload, schrijf terug naar incoming_orders.

    Doet GEEN POST naar Exact.
    """
    parsed = dict(incoming_row.get("parsed_data") or {})
    customer_name = parsed.get("customer_name") or parsed.get("customer") or ""
    lines = parsed.get("lines") or []

    customer_match = match_customer(client, customer_name)
    item_matches = match_items(client, lines)
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

    if payload is not None and confidence >= 0.9:
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
