"""Claude API order parser voor Earth Water.

Extraheert gestructureerde orderdata uit e-mail tekst en/of PDF-bijlagen
met behulp van Anthropic's Claude met prompt-caching op de system prompt.
"""
from __future__ import annotations

import base64
import json
import re
from typing import Any


OUTPUT_SCHEMA_DOC = """
{
  "customer_name": "string — bedrijfsnaam van de besteller",
  "customer_reference": "string|null — PO-nummer of referentie van de klant",
  "delivery_date": "YYYY-MM-DD|null — gewenste leverdatum",
  "delivery_address": {
    "street": "string|null",
    "zip": "string|null",
    "city": "string|null",
    "country": "string|null — 2-letter ISO of volledig, wat er staat"
  },
  "lines": [
    {
      "description": "string — productomschrijving zoals in de order",
      "item_code": "string|null — Earth Water artikelcode (zie instructies)",
      "quantity": "number — aantal eenheden",
      "unit": "string|null — doos/case/fles/pallet",
      "unit_price": "number|null — prijs per eenheid exclusief BTW"
    }
  ],
  "notes": "string|null — opmerkingen, leveringsinstructies",
  "confidence": "number 0-1 — jouw inschatting hoe zeker deze extractie klopt"
}
"""

SYSTEM_PROMPT = f"""Je bent een order-extractie-assistent voor Earth Water (premium watermerk, Exact Online administratie 746).
Je taak: uit een inkomende mail en/of PDF-bijlage bestelgegevens halen.

JSON-schema dat je MOET retourneren:
{OUTPUT_SCHEMA_DOC}

Instructies:
- Retourneer UITSLUITEND geldige JSON volgens het schema, zonder markdown-fences of commentaar.
- Als een veld niet bekend is, gebruik null (voor lijsten: lege lijst).
- Gebruik YYYY-MM-DD voor datums.
- Ga uit van EUR en BTW-exclusief tenzij anders vermeld.
- Confidence 0.9+ als alles duidelijk en compleet is; 0.7-0.9 bij kleine twijfel; <0.7 bij ontbrekende kritieke velden.

ARTIKELCODE-REGELS (kritisch):
- Earth Water-codes beginnen typisch met 'EW' (bv. EW72316) of zijn numeriek (bv. 72316, 9005, 9100). Deze horen in 'item_code'.
- Klanten gebruiken in hun PO's vaak twee code-kolommen: een met hun eigen SKU en een met de leverancierscode. Kies ALTIJD de leverancierscode (= Earth Water).
- Voorkeurskolomnamen voor item_code: 'Uw Artikelnr.', 'Uw ref', 'Art. Nr.', 'Leveranciersnummer', 'EAN/SKU leverancier', 'Supplier code'.
- NOOIT gebruiken voor item_code: 'Ons Nr.', 'Onze Artikelnr.', 'Interne SKU', 'Onze code', 'Klant-artikelnr.'.
- Als er twijfel is of geen expliciete kolomnaam, verkies een code die begint met 'EW' of die numeriek 4-5 cijfers is (typische EW-reeks), en geef de andere in 'notes' als context.
- Regels met quantity 0 of leeg horen NIET in de output (template-prijslijsten).
"""

_DEFAULTS: dict[str, Any] = {
    "customer_name": None,
    "customer_reference": None,
    "delivery_date": None,
    "delivery_address": {"street": None, "zip": None, "city": None, "country": None},
    "lines": [],
    "notes": None,
    "confidence": 0.0,
}


def _strip_html(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


def _extract_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"Geen JSON gevonden in Claude-response: {text[:200]!r}")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise ValueError(f"Kon JSON niet parsen: {e}") from e


def _apply_defaults(data: dict) -> dict:
    result = dict(_DEFAULTS)
    result["delivery_address"] = dict(_DEFAULTS["delivery_address"])
    result["lines"] = []
    for key, value in data.items():
        result[key] = value
    if "lines" not in data:
        result["lines"] = []
    if "confidence" not in data:
        result["confidence"] = 0.0

    # Template-bestellijsten (zoals Archeon) hebben alle producten als
    # regel met quantity=0 voor niet-bestelde items. Filter die weg zodat
    # matching + payload alleen de echt bestelde regels ziet.
    filtered_lines = []
    for line in result["lines"]:
        qty = line.get("quantity")
        try:
            if qty is not None and float(qty) > 0:
                filtered_lines.append(line)
        except (TypeError, ValueError):
            continue
    result["lines"] = filtered_lines
    return result


def parse_order(
    body_text: str | None = None,
    body_html: str | None = None,
    pdf_bytes: bytes | None = None,
    pdf_mime: str = "application/pdf",
    client=None,
    model: str = "claude-sonnet-4-6",
) -> dict:
    """Extraheert gestructureerde orderdata via Claude API.

    Minstens één van body_text/body_html/pdf_bytes is vereist.
    Retourneert dict volgens OUTPUT_SCHEMA_DOC.
    """
    if not any([body_text, body_html, pdf_bytes]):
        raise ValueError("Minstens één van body_text, body_html of pdf_bytes is vereist")

    if client is None:
        import anthropic

        client = anthropic.Anthropic()

    content_blocks: list[dict] = []

    if pdf_bytes:
        content_blocks.append(
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": pdf_mime,
                    "data": base64.b64encode(pdf_bytes).decode("ascii"),
                },
            }
        )

    text = body_text or (_strip_html(body_html) if body_html else None)
    if text:
        content_blocks.append({"type": "text", "text": f"Mail-tekst:\n{text}"})

    if not content_blocks:
        raise ValueError("Geen content om te versturen naar Claude")

    system_block = {
        "type": "text",
        "text": SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"},
    }

    response = client.messages.create(
        model=model,
        max_tokens=2000,
        system=[system_block],
        messages=[{"role": "user", "content": content_blocks}],
    )

    reply_text = response.content[0].text
    data = _extract_json(reply_text)
    return _apply_defaults(data)


def parse_incoming_order(row: dict, sb, client=None) -> dict:
    """Parseer één incoming_orders-rij en update de status in Supabase.

    Retourneert de bijgewerkte rij (met parse_status, parsed_data, error).
    """
    pdf_bytes = None
    attachments = row.get("attachments") or []
    # Doorgestuurde mails bevatten vaak meerdere inline-bijlagen (signature-logo,
    # tracking-pixel, e.d.). Pak alleen een echte PDF, anders stuurt Claude
    # plaatje-bytes als application/pdf en klapt de parse.
    pdf_att = next(
        (
            a for a in attachments
            if isinstance(a, dict)
            and (
                (a.get("content_type") or "").lower() == "application/pdf"
                or (a.get("filename") or "").lower().endswith(".pdf")
            )
        ),
        None,
    )
    if pdf_att:
        storage_path = pdf_att.get("storage_path")
        if storage_path:
            try:
                pdf_bytes = sb.storage.from_("order-attachments").download(storage_path)
            except Exception:
                pdf_bytes = None

    # Magic-byte check: sommige mails leveren `.msg` of `.eml` aan als
    # application/pdf, of versturen een beschadigde/encrypted PDF. Claude
    # weigert die met "The PDF specified was not valid"; parse dan op
    # alleen mail-tekst zodat de rij niet onnodig op 'failed' komt.
    if pdf_bytes and not pdf_bytes[:5] == b"%PDF-":
        pdf_bytes = None

    def _run(pdf):
        return parse_order(
            body_text=row.get("body_text"),
            body_html=row.get("body_html"),
            pdf_bytes=pdf,
            client=client,
        )

    update: dict[str, Any] = {}
    try:
        try:
            parsed = _run(pdf_bytes)
        except Exception as e:
            # Claude kan een magic-byte-geldige PDF alsnog weigeren
            # (encrypted, unsupported version). Retry zonder PDF zodat de
            # mail-tekst nog wel geparsed wordt.
            if pdf_bytes and "PDF" in str(e):
                parsed = _run(None)
            else:
                raise
        confidence = parsed.get("confidence") or 0.0
        status = "parsed" if confidence >= 0.7 else "needs_review"
        update = {
            "parse_status": status,
            "parsed_data": parsed,
            "error": None,
        }
    except Exception as e:
        update = {
            "parse_status": "failed",
            "error": str(e),
        }

    try:
        sb.table("incoming_orders").update(update).eq("id", row.get("id")).execute()
    except Exception:
        pass

    result = dict(row)
    result.update(update)
    return result
