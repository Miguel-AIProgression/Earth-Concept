"""Tests voor matcher.py — Supabase-katalogus + rapidfuzz + aliases."""

from unittest.mock import MagicMock

import matcher


def _sb_with(accounts=None, items=None, alias=None):
    """Mock Supabase-client die bekende data teruggeeft voor select-calls."""
    sb = MagicMock()

    accounts = accounts or []
    items = items or []

    def table(name):
        t = MagicMock()

        if name == "exact_accounts":
            t.select.return_value.execute.return_value = MagicMock(data=accounts)
        elif name == "exact_items":
            t.select.return_value.execute.return_value = MagicMock(data=items)
        elif name in ("customer_aliases", "item_aliases"):
            data = [alias] if (alias and alias.get("_table") == name) else []
            t.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
                data=data
            )
        return t

    sb.table.side_effect = table
    return sb


# ----- normalize_name -----


def test_normalize_strip_legal_suffix():
    assert matcher.normalize_name("Horesca Horecavo B.V.") == "horesca horecavo"
    assert matcher.normalize_name("O'Reilly & Co.") == "o reilly"
    assert matcher.normalize_name("  Earth Water   N.V.  ") == "earth water"


# ----- match_customer -----


def test_match_customer_exact_normalized():
    accounts = [
        {"id": "a1", "code": "HH", "name": "Horesca Horecavo B.V.",
         "name_normalized": "horesca horecavo", "email": None},
    ]
    sb = _sb_with(accounts=accounts)
    res = matcher.match_customer(sb, "Horesca Horecavo")
    assert res["id"] == "a1"
    assert res["confidence"] == 1.0
    assert res["source"] == "exact"


def test_match_customer_fuzzy():
    accounts = [
        {"id": "a1", "code": "HH", "name": "Horesca Horecavo B.V.",
         "name_normalized": "horesca horecavo", "email": None},
        {"id": "a2", "code": "X", "name": "Totaal andere klant",
         "name_normalized": "totaal andere klant", "email": None},
    ]
    sb = _sb_with(accounts=accounts)
    res = matcher.match_customer(sb, "Horesca Horevaco")  # typo
    assert res is not None
    assert res["id"] == "a1"
    assert res["source"] == "fuzzy"
    assert res["confidence"] > 0.85


def test_match_customer_alias_wint_van_exact():
    accounts = [
        {"id": "a1", "code": "X", "name": "Irrelevant",
         "name_normalized": "irrelevant", "email": None},
    ]
    alias = {
        "_table": "customer_aliases",
        "alias": "Horesca Horecavo",
        "alias_normalized": "horesca horecavo",
        "account_id": "a999",
    }
    sb = _sb_with(accounts=accounts, alias=alias)
    res = matcher.match_customer(sb, "Horesca Horecavo")
    assert res["id"] == "a999"
    assert res["source"] == "alias"
    assert res["confidence"] == 1.0


def test_match_customer_geen_match():
    accounts = [
        {"id": "a1", "code": "X", "name": "Niks te zien hier",
         "name_normalized": "niks te zien hier", "email": None},
    ]
    sb = _sb_with(accounts=accounts)
    assert matcher.match_customer(sb, "Compleet iets anders") is None


def test_match_customer_lege_input():
    sb = _sb_with(accounts=[])
    assert matcher.match_customer(sb, "") is None
    assert matcher.match_customer(sb, None) is None


# ----- match_item -----


def test_match_item_code_hit():
    items = [
        {"id": "i1", "code": "EW9208", "description": "EW Radisson TT 50cl",
         "description_normalized": "ew radisson tt 50cl", "unit": "DOZ"},
    ]
    sb = _sb_with(items=items)
    line = {"item_code": "EW9208", "description": "Iets anders"}
    res = matcher.match_item(sb, line, items_cache=items)
    assert res["item_id"] == "i1"
    assert res["confidence"] == 1.0
    assert res["source"] == "code"


def test_match_item_code_prefix():
    items = [
        {"id": "i1", "code": "EW9208-NL", "description": "EW TT 50cl",
         "description_normalized": "ew tt 50cl", "unit": "DOZ"},
    ]
    sb = _sb_with(items=items)
    line = {"item_code": "EW9208", "description": "TT 50cl"}
    res = matcher.match_item(sb, line, items_cache=items)
    assert res["item_id"] == "i1"
    assert res["source"] == "code-prefix"


def test_match_item_fuzzy_description():
    items = [
        {"id": "i1", "code": "EW-STILL-500", "description": "Still water 500ml fles",
         "description_normalized": "still water 500ml fles", "unit": "DOZ"},
    ]
    sb = _sb_with(items=items)
    line = {"description": "Still water 500ml flessen"}  # plural
    res = matcher.match_item(sb, line, items_cache=items)
    assert res["item_id"] == "i1"
    assert res["source"] == "fuzzy"
    assert res["confidence"] >= 0.8


def test_match_item_alias():
    items = [{"id": "i1", "code": "X", "description": "X", "description_normalized": "x", "unit": None}]
    alias = {
        "_table": "item_aliases",
        "alias": "Kopie van Bestellijst item 1",
        "alias_normalized": "kopie van bestellijst item 1",
        "item_id": "i999",
    }
    sb = _sb_with(items=items, alias=alias)
    line = {"description": "Kopie van Bestellijst item 1"}
    res = matcher.match_item(sb, line, items_cache=items)
    assert res["item_id"] == "i999"
    assert res["source"] == "alias"


def test_match_item_geen_match():
    items = [
        {"id": "i1", "code": "EW-SPARKLING-330", "description": "Sparkling 330ml blik",
         "description_normalized": "sparkling 330ml blik", "unit": "DOZ"},
    ]
    sb = _sb_with(items=items)
    line = {"item_code": "XYZ", "description": "kartonnen verhuisdoos bruin"}
    res = matcher.match_item(sb, line, items_cache=items)
    assert res["item_id"] is None
    assert res["confidence"] == 0.0
