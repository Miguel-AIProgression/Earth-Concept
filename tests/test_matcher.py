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
            t.select.return_value.range.return_value.execute.return_value = MagicMock(data=accounts)
        elif name == "exact_items":
            t.select.return_value.range.return_value.execute.return_value = MagicMock(data=items)
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


def test_match_customer_exact_met_superset_sibling_is_ambiguous():
    """Exacte naam-match is niet eenduidig als er een broertje bestaat
    waarvan alle tokens ook in de parsed naam zitten plus extra -- de
    klant wil bij twijfel handmatig bevestigen (Inbev vs Inbev Capelle)."""
    accounts = [
        {"id": "a1", "code": "1", "name": "InBev Nederland N.V.",
         "name_normalized": "inbev nederland", "email": None},
        {"id": "a2", "code": "2", "name": "Inbev Nederland NV Capelle",
         "name_normalized": "inbev nederland capelle", "email": None},
    ]
    sb = _sb_with(accounts=accounts)
    res = matcher.match_customer(sb, "Inbev Nederland NV")
    assert res is not None
    assert res["id"] == "a1"
    assert res["source"] == "exact_ambiguous"


def test_match_customer_dubbele_exacte_normalisatie_is_ambiguous():
    """Twee accounts met identieke genormaliseerde naam -> ambiguous."""
    accounts = [
        {"id": "a1", "code": "1", "name": "Hotel X B.V.",
         "name_normalized": "hotel x", "email": None},
        {"id": "a2", "code": "2", "name": "Hotel X NV",
         "name_normalized": "hotel x", "email": None},
    ]
    sb = _sb_with(accounts=accounts)
    res = matcher.match_customer(sb, "Hotel X")
    assert res["source"] == "exact_ambiguous"


def test_match_customer_fuzzy_rejects_sparse_overlap():
    """Korte kandidaten met maar 1 gedeelde token mogen niet matchen.

    'De Klok Dranken Helmond' bevat 4 tokens waarvan alleen 'dranken'
    overlapt met 'D Dranken' — token_set_ratio scoort dat alsnog 88
    maar dat is een onzinmatch en mag niet door.
    """
    accounts = [
        {"id": "a1", "code": "DD", "name": "D Dranken",
         "name_normalized": "d dranken", "email": None},
    ]
    sb = _sb_with(accounts=accounts)
    assert matcher.match_customer(sb, "De Klok Dranken Helmond") is None


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


# ----- match_customer_by_address -----


def _exact_with(addresses):
    ec = MagicMock()
    ec.get.return_value = addresses
    return ec


def test_match_customer_by_address_single_hit():
    """Postcode geeft één hit; account wordt via lokale katalogus gevonden."""
    accounts = [
        {"id": "a1", "code": "770", "name": "Exco Hotel KVK NV C/O Park inn by Radisson Leuven",
         "name_normalized": "exco hotel kvk c o park inn by radisson leuven", "email": None},
    ]
    exact = _exact_with([
        {"ID": "addr1", "Account": "a1", "AddressLine1": "Martelarenlaan 36",
         "Postcode": "3010", "City": "Leuven"},
    ])
    sb = _sb_with(accounts=accounts)
    delivery = {"street": "Martelarenlaan 36", "zip": "3010", "city": "Leuven", "country": "BE"}
    res = matcher.match_customer_by_address(exact, sb, delivery, customer_name_hint="Park Inn by Radisson, Leuven - ZGKPD")
    assert res is not None
    assert res["id"] == "a1"
    assert res["source"] == "address"
    assert res["confidence"] >= 0.90  # postcode + stad + straatfragment + naam-hint


def test_match_customer_by_address_meerdere_kiest_beste_via_naam_hint():
    accounts = [
        {"id": "a1", "code": "1", "name": "Random Leuven Hotel",
         "name_normalized": "random leuven hotel", "email": None},
        {"id": "a2", "code": "2", "name": "Park Inn by Radisson Leuven",
         "name_normalized": "park inn by radisson leuven", "email": None},
    ]
    exact = _exact_with([
        {"ID": "x", "Account": "a1", "AddressLine1": "Ander adres", "Postcode": "3010", "City": "Leuven"},
        {"ID": "y", "Account": "a2", "AddressLine1": "Martelarenlaan 36", "Postcode": "3010", "City": "Leuven"},
    ])
    sb = _sb_with(accounts=accounts)
    delivery = {"street": "Martelarenlaan 36", "zip": "3010", "city": "Leuven"}
    res = matcher.match_customer_by_address(exact, sb, delivery, customer_name_hint="Park Inn by Radisson Leuven")
    assert res["id"] == "a2"


def test_match_customer_by_address_geen_postcode_geen_match():
    sb = _sb_with(accounts=[])
    exact = _exact_with([])
    assert matcher.match_customer_by_address(exact, sb, {"city": "Leuven"}) is None
    assert matcher.match_customer_by_address(exact, sb, None) is None


def test_match_customer_by_address_geen_hits():
    accounts = [{"id": "a1", "code": "1", "name": "X", "name_normalized": "x", "email": None}]
    exact = _exact_with([])
    sb = _sb_with(accounts=accounts)
    res = matcher.match_customer_by_address(exact, sb, {"zip": "9999", "city": "Nergens"})
    assert res is None


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
