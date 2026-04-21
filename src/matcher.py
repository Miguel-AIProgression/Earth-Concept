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

CUSTOMER_FUZZY_THRESHOLD = 80
ITEM_FUZZY_THRESHOLD = 92


def _normalize_item_code(code: str | None) -> str:
    """Strip EW-prefix + whitespace zodat 72316 matcht op EW72316."""
    if not code:
        return ""
    c = code.strip().upper()
    if c.startswith("EW"):
        c = c[2:]
    return c.lstrip("0")


_PAGE_SIZE = 1000


def _fetch_paginated(sb, table: str, columns: str) -> list[dict]:
    """Haal alle rijen op in pages; Supabase retourneert max 1000 per call."""
    rows: list[dict] = []
    start = 0
    while True:
        res = (
            sb.table(table)
            .select(columns)
            .range(start, start + _PAGE_SIZE - 1)
            .execute()
        )
        batch = res.data or []
        rows.extend(batch)
        if len(batch) < _PAGE_SIZE:
            break
        start += _PAGE_SIZE
    return rows


def _fetch_accounts(sb) -> list[dict]:
    return _fetch_paginated(sb, "exact_accounts", "id,code,name,name_normalized,email")


def _fetch_items(sb) -> list[dict]:
    return _fetch_paginated(sb, "exact_items", "id,code,description,description_normalized,unit")


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

    # Exacte match op genormaliseerde naam. Als er dubbele exacte
    # matches zijn, of als de gekozen account een broertje heeft wiens
    # genormaliseerde naam een strikte supersnit van de onze is (bv.
    # "inbev nederland" vs "inbev nederland capelle"), dan is de keuze
    # niet eenduidig en vlaggen we als 'exact_ambiguous' -- auto-gate
    # laat dat door naar handmatige review.
    exact_matches = [a for a in accounts if a.get("name_normalized") == normalized]
    if exact_matches:
        chosen = exact_matches[0]
        my_tokens = set(normalized.split())
        has_duplicate = len(exact_matches) > 1
        has_superset_sibling = any(
            a["id"] != chosen["id"]
            and my_tokens < set((a.get("name_normalized") or "").split())
            for a in accounts
        )
        source = "exact_ambiguous" if (has_duplicate or has_superset_sibling) else "exact"
        return {
            "id": chosen["id"],
            "name": chosen["name"],
            "confidence": 1.0,
            "source": source,
        }

    # token_set_ratio i.p.v. WRatio — WRatio scoort korte partial substrings
    # te hoog ("ambassade hotel" vs "am" → 90; "park inn by radisson" vs
    # "by jessie jaydee" → 85) en levert dan onzinmatches. token_set_ratio
    # eist echte tokenoverlap en laat typo-tolerantie intact (rapidfuzz
    # gebruikt Levenshtein op de union-strings).
    choices = {a["id"]: a.get("name_normalized") or "" for a in accounts}
    best = process.extractOne(
        normalized,
        choices,
        scorer=fuzz.token_set_ratio,
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


def _normalize_postcode(zipcode: str | None) -> str:
    return (zipcode or "").strip().replace(" ", "").upper()


def match_customer_by_address(
    exact,
    sb,
    delivery_address: dict | None,
    customer_name_hint: str | None = None,
) -> dict | None:
    """Zoek een klant op via het afleveradres als naam-match faalt.

    Queryt Exact's /crm/Addresses op postcode (met en zonder spatie) en
    scoort kandidaat-accounts op stad- en straat-overlap + optionele
    naam-hint. source='address' — past nooit in de auto-approve gate.
    """
    if not delivery_address:
        return None
    raw_zip = (delivery_address.get("zip") or "").strip()
    if not raw_zip:
        return None

    city_target = (delivery_address.get("city") or "").strip().lower()
    street_target = (delivery_address.get("street") or "").strip().lower()
    zip_norm = _normalize_postcode(raw_zip)

    # Probeer eerst de postcode zoals ontvangen, daarna zonder spatie.
    addresses: list[dict] = []
    tried: set[str] = set()
    for pc in (raw_zip, zip_norm):
        if not pc or pc in tried:
            continue
        tried.add(pc)
        pc_escaped = pc.replace("'", "''")
        try:
            res = exact.get(
                "/crm/Addresses",
                params={
                    "$filter": f"Postcode eq '{pc_escaped}'",
                    "$select": "ID,Account,AddressLine1,Postcode,City",
                },
            ) or []
        except Exception as e:
            log.warning("Address-lookup op postcode %s faalde: %s", pc, e)
            continue
        addresses.extend(res)
        if res:
            break

    if not addresses:
        return None

    accounts_by_id = {a["id"]: a for a in _fetch_accounts(sb)}
    name_hint_norm = normalize_name(customer_name_hint) if customer_name_hint else ""

    best: tuple[int, str, dict] | None = None
    for a in addresses:
        acc_id = a.get("Account")
        acc = accounts_by_id.get(acc_id) if acc_id else None
        if not acc:
            continue
        score = 70  # postcode matcht
        addr_city = (a.get("City") or "").strip().lower()
        addr_street = (a.get("AddressLine1") or "").strip().lower()
        if city_target and addr_city and city_target == addr_city:
            score += 15
        if street_target and addr_street:
            prefix = min(8, len(street_target), len(addr_street))
            if prefix and (addr_street[:prefix] == street_target[:prefix]):
                score += 10
        if name_hint_norm:
            name_sim = fuzz.token_set_ratio(
                name_hint_norm, acc.get("name_normalized") or ""
            )
            if name_sim >= 60:
                score += min(int(name_sim * 0.05), 5)
        if best is None or score > best[0]:
            best = (score, acc_id, acc)

    if not best:
        return None
    score, acc_id, acc = best
    return {
        "id": acc_id,
        "name": acc["name"],
        "confidence": round(min(score, 100) / 100, 3),
        "source": "address",
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

    # 1. Exact code match — mét EW-prefix-normalisatie zodat
    #    '72316' matcht op 'EW72316' en vice versa.
    if code:
        target = _normalize_item_code(code)
        for it in items:
            if _normalize_item_code(it.get("code")) == target:
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
        target = _normalize_item_code(code)
        for it in items:
            it_norm = _normalize_item_code(it.get("code"))
            if target and it_norm and (it_norm.startswith(target) or target.startswith(it_norm)):
                result.update(
                    {
                        "item_id": it["id"],
                        "item_code": it.get("code"),
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
