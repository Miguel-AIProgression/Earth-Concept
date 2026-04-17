"""Klant- en artikel-matcher op basis van lokale Supabase-katalogus.

Gebruikt drie lagen in volgorde:
  1. Alias-tabel — bekende handmatige correcties.
  2. Exact match op genormaliseerde naam / code.
  3. Fuzzy (rapidfuzz WRatio) boven een drempel.

De katalogus wordt nightly ververst door catalog_sync.py; deze module
raakt Exact Online zelf niet aan — sneller én werkt ook als de Exact API
down is.
"""

from __future__ import annotations

import logging
from typing import Any

from rapidfuzz import fuzz, process

from catalog_sync import normalize_name

log = logging.getLogger(__name__)

CUSTOMER_FUZZY_THRESHOLD = 85
ITEM_FUZZY_THRESHOLD = 80


def _fetch_accounts(sb) -> list[dict]:
    res = sb.table("exact_accounts").select("id,code,name,name_normalized,email").execute()
    return res.data or []


def _fetch_items(sb) -> list[dict]:
    res = sb.table("exact_items").select("id,code,description,description_normalized,unit").execute()
    return res.data or []


def _fetch_alias(sb, table: str, alias_normalized: str) -> dict | None:
    if not alias_normalized:
        return None
    res = (
        sb.table(table)
        .select("*")
        .eq("alias_normalized", alias_normalized)
        .limit(1)
        .execute()
    )
    return (res.data or [None])[0]


def match_customer(sb, customer_name: str | None) -> dict | None:
    """Match een klantnaam op een account in de lokale katalogus."""
    if not customer_name:
        return None

    normalized = normalize_name(customer_name)
    if not normalized:
        return None

    alias = _fetch_alias(sb, "customer_aliases", normalized)
    if alias:
        return {
            "id": alias["account_id"],
            "name": customer_name,
            "confidence": 1.0,
            "source": "alias",
        }

    accounts = _fetch_accounts(sb)
    if not accounts:
        return None

    for a in accounts:
        if a.get("name_normalized") == normalized:
            return {"id": a["id"], "name": a["name"], "confidence": 1.0, "source": "exact"}

    choices = {a["id"]: a.get("name_normalized") or "" for a in accounts}
    best = process.extractOne(
        normalized,
        choices,
        scorer=fuzz.WRatio,
        score_cutoff=CUSTOMER_FUZZY_THRESHOLD,
    )
    if not best:
        return None
    _, score, account_id = best
    account = next(a for a in accounts if a["id"] == account_id)
    return {
        "id": account["id"],
        "name": account["name"],
        "confidence": round(score / 100, 3),
        "source": "fuzzy",
    }


def match_item(sb, line: dict, items_cache: list[dict] | None = None) -> dict:
    """Match één orderregel op een Exact Item."""
    code = (line.get("item_code") or "").strip()
    description = (line.get("description") or "").strip()

    result = {
        "line": line,
        "item_id": None,
        "item_code": None,
        "confidence": 0.0,
        "source": None,
    }

    alias_norm = normalize_name(description)
    if alias_norm:
        alias = _fetch_alias(sb, "item_aliases", alias_norm)
        if alias:
            result.update(
                {
                    "item_id": alias["item_id"],
                    "confidence": 1.0,
                    "source": "alias",
                }
            )
            return result

    items = items_cache if items_cache is not None else _fetch_items(sb)
    if not items:
        return result

    # 1. Exact code match
    if code:
        for it in items:
            if (it.get("code") or "").strip() == code:
                result.update(
                    {
                        "item_id": it["id"],
                        "item_code": it.get("code"),
                        "confidence": 1.0,
                        "source": "code",
                    }
                )
                return result

    # 2. Code-prefix (klant stuurt EW9208, Exact heeft EW9208-NL)
    if code:
        for it in items:
            it_code = (it.get("code") or "").strip()
            if it_code and (it_code.startswith(code) or code.startswith(it_code)):
                result.update(
                    {
                        "item_id": it["id"],
                        "item_code": it_code,
                        "confidence": 0.9,
                        "source": "code-prefix",
                    }
                )
                return result

    # 3. Fuzzy op description
    if description:
        normalized = normalize_name(description)
        choices = {it["id"]: it.get("description_normalized") or "" for it in items}
        best = process.extractOne(
            normalized,
            choices,
            scorer=fuzz.WRatio,
            score_cutoff=ITEM_FUZZY_THRESHOLD,
        )
        if best:
            _, score, item_id = best
            it = next(i for i in items if i["id"] == item_id)
            result.update(
                {
                    "item_id": it["id"],
                    "item_code": it.get("code"),
                    "confidence": round(score / 100, 3),
                    "source": "fuzzy",
                }
            )

    return result


def match_items(sb, lines: list[dict]) -> list[dict]:
    """Match alle orderregels; laadt de item-katalogus één keer."""
    items_cache = _fetch_items(sb)
    return [match_item(sb, line, items_cache=items_cache) for line in lines]


def record_customer_alias(sb, alias: str, account_id: str, source: str = "manual") -> None:
    """Leg een klantnaam-alias vast zodat volgende keer directe match lukt."""
    norm = normalize_name(alias)
    if not norm or not account_id:
        return
    sb.table("customer_aliases").upsert(
        {
            "alias": alias,
            "alias_normalized": norm,
            "account_id": account_id,
            "source": source,
        },
        on_conflict="alias_normalized",
    ).execute()


def record_item_alias(sb, alias: str, item_id: str, source: str = "manual") -> None:
    norm = normalize_name(alias)
    if not norm or not item_id:
        return
    sb.table("item_aliases").upsert(
        {
            "alias": alias,
            "alias_normalized": norm,
            "item_id": item_id,
            "source": source,
        },
        on_conflict="alias_normalized",
    ).execute()
