"""Sync Exact Online Accounts en Items naar Supabase.

Draait nightly via GitHub Actions (.github/workflows/catalog-sync.yml).
Houdt een lokale katalogus bij zodat de matcher niet meer live Exact hoeft
te bevragen — sneller, stabieler, en basis voor self-learning aliases.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Iterable

from dotenv import load_dotenv

log = logging.getLogger(__name__)

BATCH_SIZE = 200

_LEGAL_SUFFIX_RE = re.compile(
    r"\b(b\.?v\.?|n\.?v\.?|v\.?o\.?f\.?|c\.?v\.?|ltd|limited|gmbh|s\.?a\.?|sas|sarl|inc|llc|co\.?)\b",
    re.IGNORECASE,
)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def normalize_name(value: str | None) -> str:
    """Lowercase, verwijder legal suffixes en alles behalve alfanumeriek."""
    if not value:
        return ""
    text = value.lower()
    text = _LEGAL_SUFFIX_RE.sub(" ", text)
    text = _NON_ALNUM_RE.sub(" ", text)
    return " ".join(text.split())


def _batched(rows: list[dict], size: int) -> Iterable[list[dict]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def sync_accounts(exact, sb) -> int:
    """Haal alle actieve Accounts op uit Exact en upsert in Supabase."""
    results = exact.get(
        "/crm/Accounts",
        params={
            "$select": "ID,Code,Name,Email,Status",
            "$filter": "Status eq '1' or Status eq 'C' or Status eq 'A'",
        },
    )
    # Als het $filter op Status niet werkt voor deze administratie,
    # val terug op alles en laat `is_active` op True staan.
    if not results:
        results = exact.get(
            "/crm/Accounts",
            params={"$select": "ID,Code,Name,Email,Status"},
        )

    rows = []
    for a in results:
        name = a.get("Name") or ""
        if not name.strip():
            continue
        rows.append(
            {
                "id": a.get("ID"),
                "code": a.get("Code"),
                "name": name,
                "name_normalized": normalize_name(name),
                "email": a.get("Email"),
                "is_active": a.get("Status") not in ("D",),
                "raw": a,
            }
        )

    for batch in _batched(rows, BATCH_SIZE):
        sb.table("exact_accounts").upsert(batch, on_conflict="id").execute()

    log.info("Accounts gesynced: %d", len(rows))
    return len(rows)


def sync_items(exact, sb) -> int:
    """Haal alle Items op uit Exact en upsert in Supabase."""
    results = exact.get(
        "/logistics/Items",
        params={
            "$select": "ID,Code,Description,Unit,Barcode,IsSalesItem,IsSalesItemOnly",
            "$filter": "IsSalesItem eq true",
        },
    )
    if not results:
        results = exact.get(
            "/logistics/Items",
            params={"$select": "ID,Code,Description,Unit,Barcode"},
        )

    rows = []
    for it in results:
        desc = it.get("Description") or ""
        if not desc.strip():
            continue
        rows.append(
            {
                "id": it.get("ID"),
                "code": it.get("Code"),
                "description": desc,
                "description_normalized": normalize_name(desc),
                "unit": it.get("Unit"),
                "barcode": it.get("Barcode"),
                "is_active": True,
                "raw": it,
            }
        )

    for batch in _batched(rows, BATCH_SIZE):
        sb.table("exact_items").upsert(batch, on_conflict="id").execute()

    log.info("Items gesynced: %d", len(rows))
    return len(rows)


def run() -> dict:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

    from supabase import create_client
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

    from exact_client import ExactClient
    exact = ExactClient()

    accounts = sync_accounts(exact, sb)
    items = sync_items(exact, sb)

    stats = {"accounts": accounts, "items": items}
    log.info("Catalog sync klaar: %s", stats)
    return stats


if __name__ == "__main__":
    stats = run()
    print(stats)
