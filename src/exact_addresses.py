"""Zet een vrij-tekst afleveradres om naar een Exact Address-GUID.

Exact's SalesOrder-POST accepteert alleen een Address-GUID in
``DeliveryAddress``; losse straat/postcode/stad kunnen niet inline worden
meegestuurd. We maken (of hergebruiken) daarom een Address-record van
Type 4 (Delivery) op de OrderedBy-account en retourneren de GUID.

Bij fouten of onvoldoende data: None — de caller laat ``DeliveryAddress``
dan weg en Exact valt terug op het default-afleveradres van de account.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# Exact address types
ADDRESS_TYPE_DELIVERY = 4

_COUNTRY_ALIASES = {
    "NEDERLAND": "NL",
    "HOLLAND": "NL",
    "NETHERLANDS": "NL",
    "THE NETHERLANDS": "NL",
    "BELGIE": "BE",
    "BELGIUM": "BE",
    "DEUTSCHLAND": "DE",
    "GERMANY": "DE",
    "DUITSLAND": "DE",
    "FRANCE": "FR",
    "FRANKRIJK": "FR",
    "UNITED KINGDOM": "GB",
    "GREAT BRITAIN": "GB",
    "VERENIGD KONINKRIJK": "GB",
    "ENGLAND": "GB",
    "LUXEMBURG": "LU",
    "LUXEMBOURG": "LU",
    "ITALY": "IT",
    "ITALIE": "IT",
    "ITALIA": "IT",
    "SPAIN": "ES",
    "SPANJE": "ES",
    "ESPANA": "ES",
    "OOSTENRIJK": "AT",
    "AUSTRIA": "AT",
}


def _normalize_country(country: str | None) -> str | None:
    if not country:
        return None
    c = country.strip().upper().replace("Ë", "E").replace("É", "E")
    if len(c) == 2 and c.isalpha():
        return c
    return _COUNTRY_ALIASES.get(c)


def _normalize_postcode(zipcode: str | None) -> str:
    return (zipcode or "").strip().replace(" ", "").upper()


def _find_existing_address(
    exact, account_id: str, street: str, zipcode: str, city: str
) -> str | None:
    """Zoek een Type=4-adres voor deze Account dat al matcht op straat+postcode+stad."""
    try:
        addresses = exact.get(
            "/crm/Addresses",
            params={
                "$filter": (
                    f"Account eq guid'{account_id}' and Type eq {ADDRESS_TYPE_DELIVERY}"
                ),
                "$select": "ID,AddressLine1,Postcode,City",
            },
        ) or []
    except Exception as e:
        log.warning("Adres-lookup mislukt voor account %s: %s", account_id, e)
        return None

    target_zip = _normalize_postcode(zipcode)
    target_street = street.strip().lower()
    target_city = city.strip().lower()
    for a in addresses:
        if (
            (a.get("AddressLine1") or "").strip().lower() == target_street
            and _normalize_postcode(a.get("Postcode")) == target_zip
            and (a.get("City") or "").strip().lower() == target_city
        ):
            return a.get("ID")
    return None


def ensure_delivery_address_id(
    exact, account_id: str, addr: dict | None
) -> str | None:
    """Lever een Address-GUID voor het afleveradres uit de mail/PDF.

    Hergebruikt een bestaand Type=4-adres als straat+postcode+stad al
    matchen; anders wordt een nieuw Address-record aangemaakt.
    Retourneert None als essentiële velden ontbreken of de call faalt.
    """
    if not addr or not account_id:
        return None

    street = (addr.get("street") or "").strip()
    city = (addr.get("city") or "").strip()
    zipcode = (addr.get("zip") or "").strip()
    country_raw = (addr.get("country") or "").strip()

    # Straat + stad zijn het minimum; zonder die twee heeft een adres
    # geen waarde voor de logistieke partner.
    if not street or not city:
        return None

    existing = _find_existing_address(exact, account_id, street, zipcode, city)
    if existing:
        return existing

    payload: dict[str, Any] = {
        "Account": account_id,
        "Type": ADDRESS_TYPE_DELIVERY,
        "AddressLine1": street,
        "City": city,
        "Main": False,
    }
    if zipcode:
        payload["Postcode"] = zipcode
    country_code = _normalize_country(country_raw)
    if country_code:
        payload["Country"] = country_code

    try:
        resp = exact.post("/crm/Addresses", payload)
    except Exception as e:
        log.warning("Address-aanmaak mislukt voor account %s: %s", account_id, e)
        return None

    if isinstance(resp, dict):
        return resp.get("ID")
    return None
