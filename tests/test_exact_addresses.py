"""Tests voor exact_addresses.ensure_delivery_address_id."""

from unittest.mock import MagicMock

from exact_addresses import ensure_delivery_address_id


def _client(existing=None, post_result=None):
    c = MagicMock()
    c.get.return_value = existing or []
    c.post.return_value = post_result or {"ID": "new-guid"}
    return c


def test_retourneert_none_zonder_adres():
    c = _client()
    assert ensure_delivery_address_id(c, "acc-1", None) is None
    assert ensure_delivery_address_id(c, "acc-1", {}) is None
    c.post.assert_not_called()


def test_retourneert_none_zonder_account():
    c = _client()
    addr = {"street": "Antennestraat 55", "zip": "1322AG", "city": "Almere"}
    assert ensure_delivery_address_id(c, "", addr) is None


def test_retourneert_none_zonder_straat_of_stad():
    c = _client()
    assert ensure_delivery_address_id(c, "acc", {"street": "Only", "city": ""}) is None
    assert ensure_delivery_address_id(c, "acc", {"street": "", "city": "Almere"}) is None
    c.post.assert_not_called()


def test_maakt_nieuw_adres_als_niets_bestaat():
    c = _client(existing=[], post_result={"ID": "new-guid"})
    addr = {
        "street": "Antennestraat 55",
        "zip": "1322 AG",
        "city": "Almere",
        "country": "Nederland",
    }
    result = ensure_delivery_address_id(c, "acc-1", addr)
    assert result == "new-guid"

    c.post.assert_called_once()
    endpoint, payload = c.post.call_args.args
    assert endpoint == "/crm/Addresses"
    assert payload["Account"] == "acc-1"
    assert payload["Type"] == 4
    assert payload["AddressLine1"] == "Antennestraat 55"
    assert payload["City"] == "Almere"
    assert payload["Postcode"] == "1322 AG"
    assert payload["Country"] == "NL"
    assert payload["Main"] is False


def test_hergebruikt_bestaand_adres():
    existing = [
        {
            "ID": "existing-guid",
            "AddressLine1": "Antennestraat 55",
            "Postcode": "1322AG",
            "City": "Almere",
        }
    ]
    c = _client(existing=existing)
    addr = {"street": "Antennestraat 55", "zip": "1322 AG", "city": "Almere"}
    assert ensure_delivery_address_id(c, "acc-1", addr) == "existing-guid"
    c.post.assert_not_called()


def test_kleine_verschillen_in_case_en_spatie_matchen_bestaand_adres():
    existing = [
        {
            "ID": "existing-guid",
            "AddressLine1": "antennestraat 55",
            "Postcode": " 1322ag ",
            "City": "ALMERE",
        }
    ]
    c = _client(existing=existing)
    addr = {"street": "Antennestraat 55", "zip": "1322 AG", "city": "Almere"}
    assert ensure_delivery_address_id(c, "acc-1", addr) == "existing-guid"


def test_valt_terug_op_post_als_lookup_faalt():
    c = MagicMock()
    c.get.side_effect = RuntimeError("Exact API down")
    c.post.return_value = {"ID": "new-guid"}
    addr = {"street": "Straat 1", "zip": "1000AA", "city": "Amsterdam"}
    assert ensure_delivery_address_id(c, "acc", addr) == "new-guid"


def test_retourneert_none_als_post_faalt():
    c = MagicMock()
    c.get.return_value = []
    c.post.side_effect = RuntimeError("500")
    addr = {"street": "Straat 1", "zip": "1000AA", "city": "Amsterdam"}
    assert ensure_delivery_address_id(c, "acc", addr) is None


def test_country_blijft_weg_als_onbekend():
    c = _client(existing=[], post_result={"ID": "g"})
    addr = {"street": "Via Roma 1", "zip": "00100", "city": "Roma", "country": "Narnia"}
    ensure_delivery_address_id(c, "acc", addr)
    payload = c.post.call_args.args[1]
    assert "Country" not in payload


def test_twee_letter_country_wordt_doorgezet():
    c = _client(existing=[], post_result={"ID": "g"})
    addr = {"street": "Rue 1", "zip": "75001", "city": "Paris", "country": "fr"}
    ensure_delivery_address_id(c, "acc", addr)
    assert c.post.call_args.args[1]["Country"] == "FR"
