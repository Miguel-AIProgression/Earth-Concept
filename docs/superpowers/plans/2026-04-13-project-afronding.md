# Earth Water — Project Afronding Implementatieplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Het Earth Water orderverwerkings-project afronden: OAuth stabiel maken, dashboard consolideren, EDI-klanten uitsluiten, mail-intake bouwen, logistieke doorzetting + terugkoppeling afhandelen, en facturatie triggeren op basis van het dagelijkse leverancier-Excel.

**Architecture:** Python workers (sync, parsing, invoicing) + Next.js dashboard op Supabase. n8n/Claude API voor mail parsing. Exact Online REST API voor orders, deliveries, invoices. GitHub Actions voor scheduling.

**Tech Stack:** Python 3.11, Exact Online REST API, Supabase (Postgres + Storage), Next.js 15 dashboard, Claude API (parsing), GitHub Actions (scheduling), IMAP/Gmail API (mail intake).

---

## Openstaande punten (samenvatting klantfeedback 2026-04-13)

1. **Exact OAuth herstellen** — opnieuw inloggen via `exact_auth.py`, daarna volledig automatisch refreshen (geen handmatige interventie meer).
2. **Semso vs handmatig onderscheid verwijderen** — "Kantoor EARTH" en "Patrick de Nekker" zijn gewoon verschillende Exact-gebruikers die dezelfde soort orders plaatsen. Verwerking moet identiek zijn.
3. **JET-EDI klanten uitsluiten** — deze klanten lopen volledig EDI/automatisch. Onze automatisering moet ze negeren.
4. **Mail-intake bouwen** — `orders@earthwater.nl` is aangemaakt. Alle inkomende orders moeten hier binnenkomen en automatisch als SalesOrder in Exact aangemaakt worden.
5. **Doorzetten naar leverancier (Delta Wijnen)** — na ordercreatie automatisch GoodsDelivery aanmaken en statusupdates (ontvangen/verzonden/geleverd) terugsynchroniseren.
6. **Facturatie op basis van leverancier-Excel** — dagelijks Excel-bestand van leverancier (3e tabblad = geleverd). Op basis daarvan de factuur in Exact aanmaken en versturen (houd rekening met verschillen, bv. transportschade).

---

## File Structure

**Nieuw:**
- `edi_exclusions.py` — EDI-klantlijst uit `JET_EDI - Earth Concepts.xlsx` laden + helper `is_edi_customer(name)`.
- `mail_intake.py` — IMAP/Gmail poller voor `orders@earthwater.nl`, haalt mails + bijlagen op.
- `order_parser.py` — Claude API parser: mail/PDF → gestructureerde orderdata.
- `order_creator.py` — Match klant + artikelen, maak SalesOrder in Exact.
- `invoice_from_delivery.py` — Verwerk leverancier-Excel, maak SalesInvoices in Exact.
- `delivery_status_sync.py` — Synchroniseer delivery-terugkoppeling (ontvangen/verzonden/geleverd) naar Supabase.
- `tests/test_edi_exclusions.py`, `tests/test_order_parser.py`, `tests/test_order_creator.py`, `tests/test_invoice_from_delivery.py`.
- `.github/workflows/mail-intake.yml`, `.github/workflows/invoice-delivery.yml`.

**Wijzigen:**
- `exact_auth.py` — robuuste token refresh (expiry-check, proactief refreshen, concurrency-safe).
- `sync_orders.py` — `classify_source()` vervangen door `is_edi_customer()`-filter; verwijder semso/manual split.
- `auto_delivery.py` — niet langer filteren op `CreatorFullName == "Kantoor EARTH"`, maar op alle niet-EDI orders.
- `dashboard/src/app/orders/page.tsx` + API routes — semso/manual toggle weg, één orderlijst met EDI gefilterd.
- `sync_incremental.py` — zelfde classificatie-aanpassing.

---

## Task 1: Exact OAuth — automatisch refreshen zonder handmatige code

**Files:**
- Modify: `exact_auth.py`
- Modify: `exact_client.py` (als daar ook token-logic zit)
- Test: `tests/test_exact_auth.py` (nieuw)

**Probleem nu:** `get_access_token()` doet onvoorwaardelijk een refresh bij elke call (regel 82-83). Geen expiry-check, geen foutafhandeling als refresh_token verloopt. Gebruiker moet handmatig opnieuw inloggen.

- [ ] **Stap 1: Failing test — token wordt alleen gerefreshed als verlopen**

```python
# tests/test_exact_auth.py
from unittest.mock import patch
import time
from exact_auth import get_access_token

def test_geldig_token_niet_gerefreshed():
    tokens = {"access_token": "abc", "refresh_token": "r",
              "expires_at": time.time() + 600}
    with patch("exact_auth.load_tokens", return_value=tokens), \
         patch("exact_auth.refresh_access_token") as mock_refresh:
        assert get_access_token() == "abc"
        mock_refresh.assert_not_called()

def test_verlopen_token_wel_gerefreshed():
    tokens = {"access_token": "oud", "refresh_token": "r",
              "expires_at": time.time() - 10}
    new = {"access_token": "nieuw", "refresh_token": "r2",
           "expires_at": time.time() + 600}
    with patch("exact_auth.load_tokens", return_value=tokens), \
         patch("exact_auth.refresh_access_token", return_value=new):
        assert get_access_token() == "nieuw"
```

- [ ] **Stap 2: Run test — verwacht FAIL**

Run: `pytest tests/test_exact_auth.py -v`

- [ ] **Stap 3: `save_tokens` verrijken met `expires_at`**

In `save_tokens(tokens)` voor het wegschrijven:
```python
tokens["expires_at"] = time.time() + int(tokens.get("expires_in", 600)) - 30
```
(30s marge voorkomt race met server-expiry.)

- [ ] **Stap 4: `get_access_token()` herschrijven**

```python
def get_access_token():
    tokens = load_tokens()
    if not tokens:
        raise RuntimeError("Geen tokens — draai exact_auth.py handmatig voor eerste login")
    if tokens.get("expires_at", 0) > time.time():
        return tokens["access_token"]
    refreshed = refresh_access_token(tokens["refresh_token"])
    if not refreshed:
        raise RuntimeError("Refresh mislukt — refresh_token verlopen, handmatig opnieuw inloggen")
    return refreshed["access_token"]
```

- [ ] **Stap 5: Alert bij refresh-falen**

In `refresh_access_token` bij HTTP 400/401: roep `alerts.py` aan (mail/Slack naar Miguel + Patrick) zodat herinlog snel gebeurt.

- [ ] **Stap 6: Run tests + echte herinlog**

```bash
pytest tests/test_exact_auth.py -v
python exact_auth.py   # eenmalige handmatige herinlog
```

- [ ] **Stap 7: Commit**

```bash
git add exact_auth.py tests/test_exact_auth.py alerts.py
git commit -m "fix: robuuste token refresh met expiry-check en alert"
```

---

## Task 2: EDI-klanten uitsluiten van automatisering

**Files:**
- Create: `edi_exclusions.py`
- Create: `tests/test_edi_exclusions.py`
- Modify: `sync_orders.py:40-44`, `sync_incremental.py`, `auto_delivery.py:21-23`

- [ ] **Stap 1: EDI-klantnamen extraheren uit `JET_EDI - Earth Concepts.xlsx`**

```bash
python -c "import pandas as pd; df = pd.read_excel('JET_EDI - Earth Concepts.xlsx'); print(df.columns.tolist()); print(df.head(30))"
```
Noteer de kolom met klantnamen + eventuele debiteurnummers.

- [ ] **Stap 2: Failing test**

```python
# tests/test_edi_exclusions.py
from edi_exclusions import is_edi_customer, load_edi_customers

def test_edi_klant_herkend():
    assert is_edi_customer("Albert Heijn B.V.") is True

def test_niet_edi_klant():
    assert is_edi_customer("Minor Hotels Europe") is False

def test_case_insensitive_en_whitespace():
    assert is_edi_customer("  albert heijn b.v. ") is True
```

- [ ] **Stap 3: Implementatie**

```python
# edi_exclusions.py
from functools import lru_cache
import pandas as pd

EDI_FILE = "JET_EDI - Earth Concepts.xlsx"

@lru_cache(maxsize=1)
def load_edi_customers() -> set[str]:
    df = pd.read_excel(EDI_FILE)
    col = next(c for c in df.columns if "naam" in c.lower() or "name" in c.lower())
    return {str(n).strip().lower() for n in df[col].dropna()}

def is_edi_customer(name: str | None) -> bool:
    if not name:
        return False
    return name.strip().lower() in load_edi_customers()
```

- [ ] **Stap 4: Test groen**

Run: `pytest tests/test_edi_exclusions.py -v`

- [ ] **Stap 5: Sync & auto_delivery gebruiken de filter**

In `sync_orders.py`: verwijder `classify_source()`. Filter in `sync_all`:
```python
from edi_exclusions import is_edi_customer
orders = [o for o in orders if not is_edi_customer(o.get("OrderedByName"))]
```
Zelfde in `sync_incremental.py` en in `auto_delivery.get_open_kantoor_orders` (rename naar `get_open_orders`, filter EDI eruit i.p.v. filteren op Kantoor EARTH).

- [ ] **Stap 6: DB-veld `source` verwijderen of leeg laten**

Migratie Supabase: laat kolom `source` bestaan voor historie, maar vul hem niet meer. Of: `ALTER TABLE orders DROP COLUMN source;` als niks ervan afhangt. Check dashboard eerst (Task 3).

- [ ] **Stap 7: Commit**

```bash
git add edi_exclusions.py tests/test_edi_exclusions.py sync_orders.py sync_incremental.py auto_delivery.py
git commit -m "feat: EDI-klanten uitsluiten van automatisering"
```

---

## Task 3: Dashboard — Semso/Handmatig onderscheid verwijderen

**Files:**
- Modify: `dashboard/src/app/orders/page.tsx`
- Modify: `dashboard/src/app/api/orders/route.ts` (en zusters)
- Modify: componenten die filteren op `source`

- [ ] **Stap 1: Zoek waar op source gefilterd wordt**

```bash
grep -rn "source" dashboard/src
grep -rn "semso\|manual\|Kantoor EARTH" dashboard/src
```

- [ ] **Stap 2: Filters verwijderen**

Vervang twee tabs/tabellen door één orderlijst. Behoud wel filter op status en zoek op klantnaam. Als er een badge "semso/handmatig" is: vervang door niets (of door `creator` als info).

- [ ] **Stap 3: Dev-server starten en visueel checken**

```bash
cd dashboard && npm run dev
```
Open http://localhost:3000/orders. Controleer: één lijst, geen EDI-klanten zichtbaar, verzendknop werkt nog.

- [ ] **Stap 4: Commit**

```bash
git add dashboard/src
git commit -m "refactor: dashboard toont één orderlijst zonder semso/handmatig split"
```

---

## Task 4: Mail-intake bouwen — `orders@earthwater.nl`

**Files:**
- Create: `mail_intake.py`
- Create: `tests/test_mail_intake.py`
- Create: `.github/workflows/mail-intake.yml`
- Modify: Supabase schema — tabel `incoming_orders` (raw mail + bijlagen + parse status)

**Vraag vooraf aan Patrick:** is `orders@earthwater.nl` Gmail of Microsoft 365? Credentials nodig (app-password of OAuth).

- [ ] **Stap 1: Supabase migratie**

```sql
create table incoming_orders (
  id uuid primary key default gen_random_uuid(),
  received_at timestamptz not null,
  message_id text unique not null,
  from_address text,
  subject text,
  body_text text,
  body_html text,
  attachments jsonb,           -- [{name, storage_path, mime}]
  parse_status text default 'pending',  -- pending|parsed|failed|approved|created
  parsed_data jsonb,
  exact_order_id text,
  error text,
  created_at timestamptz default now()
);
```

- [ ] **Stap 2: Test — mail wordt opgeslagen en niet dubbel verwerkt**

```python
# tests/test_mail_intake.py
from unittest.mock import MagicMock
from mail_intake import process_message

def test_bekend_message_id_skippen():
    sb = MagicMock()
    sb.table().select().eq().execute.return_value.data = [{"id": "x"}]
    msg = {"Message-ID": "<abc@x>", "From": "a@b", "Subject": "s",
           "body_text": "", "body_html": "", "attachments": []}
    assert process_message(sb, msg) == "skipped"
```

- [ ] **Stap 3: `mail_intake.py` — poller**

Gebruik `imaplib` (Gmail/Outlook) of Gmail API. Per nieuwe mail in INBOX:
1. Check `message_id` al in `incoming_orders` — zo ja, skip.
2. Upload bijlagen naar Supabase Storage bucket `order-attachments/<message_id>/<filename>`.
3. Insert rij in `incoming_orders` met `parse_status='pending'`.
4. Markeer mail als gelezen (niet verplaatsen — Patrick wil zelf kunnen meelezen).

- [ ] **Stap 4: GitHub Action (elke 10 min)**

```yaml
# .github/workflows/mail-intake.yml
name: Mail intake
on:
  schedule: [{cron: "*/10 * * * *"}]
  workflow_dispatch:
jobs:
  intake:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.11"}
      - run: pip install -r requirements.txt
      - run: python mail_intake.py
        env:
          MAIL_USER: ${{ secrets.ORDERS_MAIL_USER }}
          MAIL_PASS: ${{ secrets.ORDERS_MAIL_APP_PASSWORD }}
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
```

- [ ] **Stap 5: Commit**

```bash
git add mail_intake.py tests/test_mail_intake.py .github/workflows/mail-intake.yml
git commit -m "feat: mail intake voor orders@earthwater.nl naar Supabase"
```

---

## Task 5: Order parser (Claude API)

**Files:**
- Create: `order_parser.py`
- Create: `tests/test_order_parser.py`
- Test-fixtures: gebruik `voorbeelden/2603240334.pdf` en `voorbeelden/Order Week 15.eml`

- [ ] **Stap 1: Verwachte JSON-structuur definiëren**

```python
# order_parser.py - schema
SCHEMA = {
    "customer_name": str,
    "customer_reference": str | None,
    "delivery_date": "YYYY-MM-DD or null",
    "delivery_address": {"street": str, "zip": str, "city": str, "country": str},
    "lines": [{"description": str, "quantity": int, "unit": str, "item_code": str | None, "unit_price": float | None}],
    "notes": str | None,
    "confidence": float   # 0-1
}
```

- [ ] **Stap 2: Failing test met vaste fixture (echte PDF)**

```python
def test_minor_hotels_po_parsed():
    pdf_bytes = open("voorbeelden/2603240334.pdf", "rb").read()
    result = parse_order(pdf_bytes=pdf_bytes, mime="application/pdf")
    assert result["customer_reference"] == "4600122152"
    assert len(result["lines"]) >= 1
    assert result["confidence"] >= 0.7
```

- [ ] **Stap 3: Implementatie met Claude API (prompt caching)**

Gebruik `anthropic` SDK, `claude-sonnet-4-6`. Systeem-prompt bevat het JSON-schema + voorbeelden (cached). User-content = PDF als document block of mailtekst.

- [ ] **Stap 4: Test groen + minimaal 3 fixtures**

Voeg 2 extra voorbeeld-orders toe aan `voorbeelden/`. Test alle drie.

- [ ] **Stap 5: Commit**

```bash
git add order_parser.py tests/test_order_parser.py voorbeelden/
git commit -m "feat: AI order parsing uit PDF en mail"
```

---

## Task 6: SalesOrder aanmaken in Exact

**Files:**
- Create: `order_creator.py`
- Create: `tests/test_order_creator.py`

- [ ] **Stap 1: Klant- en artikelmatching met review-gate**

Logica:
1. `parsed.customer_name` → Exact `/crm/Accounts?$filter=Name eq '...'` (fuzzy fallback).
2. Per regel `parsed.item_code` of `description` → `/logistics/Items`.
3. Als matching-confidence < 0.9 of klant onbekend: `parse_status='needs_review'`, dashboard toont review-kaart.

- [ ] **Stap 2: Test — SalesOrder payload correct**

```python
def test_salesorder_payload():
    parsed = {...}
    account_id = "guid-1"
    items = {"EW-500": "item-guid-1"}
    payload = build_salesorder_payload(parsed, account_id, items)
    assert payload["OrderedBy"] == account_id
    assert payload["SalesOrderLines"][0]["Item"] == "item-guid-1"
    assert payload["YourRef"] == parsed["customer_reference"]
```

- [ ] **Stap 3: POST naar `/salesorder/SalesOrders`**

Alleen wanneer `parse_status='approved'` (Patrick klikt goedkeuren in dashboard). Daarna `parse_status='created'` + `exact_order_id` opslaan.

- [ ] **Stap 4: Dashboard review-queue**

Route `/dashboard/src/app/intake/page.tsx` met de `incoming_orders` met status `pending`/`needs_review`. Knop "Goedkeuren → Exact".

- [ ] **Stap 5: End-to-end test met testmail**

Stuur een testmail naar `orders@earthwater.nl` → binnen 10 min in dashboard → goedkeuren → order in Exact (testdivisie).

- [ ] **Stap 6: Commit**

```bash
git add order_creator.py tests/test_order_creator.py dashboard/src/app/intake
git commit -m "feat: SalesOrder aanmaken vanuit mail-intake met review-gate"
```

---

## Task 7: Doorzetten naar leverancier + terugkoppeling

**Files:**
- Modify: `auto_delivery.py` (zie Task 2 voor filter)
- Create: `delivery_status_sync.py`
- Modify: Supabase schema — kolommen `delivery_received_at`, `shipped_at`, `delivered_at` op `orders`

**Werking bevestigen bij Patrick:**
- Hoe komt de leverancier-terugkoppeling binnen? Mail? Exact-update door leverancier? Delta Wijnen portal?
- Aanname nu: Delta Wijnen update `DeliveryStatus` op de order in Exact (ontvangen → verzonden → geleverd).

- [ ] **Stap 1: Bestaande auto_delivery draait al — verifieer op niet-EDI orders**

```bash
python auto_delivery.py --dry-run
```
Verwacht: lijst met orders zonder EDI-klanten.

- [ ] **Stap 2: `delivery_status_sync.py` — statussen ophalen**

Haal `DeliveryStatus`, `DeliveryStatusDescription` per order op (bulk via `$filter=OrderDate ge ...`). Update `orders.delivery_status_description` in Supabase. Timestamp-velden invullen bij eerste transitie.

- [ ] **Stap 3: Alert bij stagnatie**

Orders > 5 dagen in status "verzonden" zonder "geleverd" → `alerts.py` mail naar Patrick.

- [ ] **Stap 4: Cron elke 2 uur via GitHub Actions**

Gebruik bestaande `sync-orders.yml` of voeg toe. Incrementeel, niet volledige 2026-sync.

- [ ] **Stap 5: Commit**

```bash
git add delivery_status_sync.py .github/workflows/
git commit -m "feat: delivery status terugsync van Exact naar Supabase"
```

---

## Task 8: Facturatie op basis van leverancier-Excel

**Files:**
- Create: `invoice_from_delivery.py`
- Create: `tests/test_invoice_from_delivery.py`
- Bestand: `EARTHWATER Order Exportbericht 2021 (2).xls` (3e tabblad = geleverd)

**Vraag aan Patrick:**
- Hoe komt het Excel dagelijks binnen? (mailbijlage → zelfde mailbox? SFTP? handmatig uploaden?)
- Gebruikt hij nu altijd dit format? Welke kolommen: ordernr klant, artikelcode, aantal geleverd, leverdatum?

- [ ] **Stap 1: Excel-structuur verkennen**

```bash
python -c "import pandas as pd; xls = pd.ExcelFile('EARTHWATER Order Exportbericht 2021 (2).xls'); print(xls.sheet_names); [print(s, pd.read_excel(xls, sheet_name=s).head()) for s in xls.sheet_names]"
```
Documenteer kolomnamen van tabblad 3 in een comment.

- [ ] **Stap 2: Failing test — matching order ↔ Excel-regel**

```python
def test_match_delivery_to_order():
    excel_rows = [{"order_nr": "SO20260001", "item": "EW-500", "delivered": 120}]
    exact_orders = [{"OrderNumber": "SO20260001", "lines": [{"ItemCode": "EW-500", "Quantity": 120}]}]
    matches, discrepancies = match_deliveries(excel_rows, exact_orders)
    assert len(matches) == 1 and not discrepancies
```

- [ ] **Stap 3: Failing test — verschil detecteren (transportschade)**

```python
def test_verschil_gedetecteerd():
    excel_rows = [{"order_nr": "SO20260001", "item": "EW-500", "delivered": 100}]
    exact_orders = [{"OrderNumber": "SO20260001", "lines": [{"ItemCode": "EW-500", "Quantity": 120}]}]
    _, discrepancies = match_deliveries(excel_rows, exact_orders)
    assert discrepancies[0]["shortage"] == 20
```

- [ ] **Stap 4: Implementatie + invoice creation**

Per matching order (geen openstaande verschillen): POST `/salesinvoice/SalesInvoices` met geleverde aantallen. Bij verschil: flag in Supabase `invoice_holds`, dashboard-kaart voor Patrick om handmatig goed te keuren.

- [ ] **Stap 5: Automatisch versturen in Exact**

Na creatie: `/salesinvoice/SalesInvoices(...)/Send` of equivalente endpoint. (Verifieer bij Patrick of hij review wil voor verzending in de eerste 2 weken.)

- [ ] **Stap 6: GitHub Action dagelijks 07:00**

```yaml
# .github/workflows/invoice-delivery.yml
on:
  schedule: [{cron: "0 6 * * 1-6"}]   # 07:00 NL, ma-za
```

- [ ] **Stap 7: End-to-end test op testdivisie**

Gebruik testbestand + testorder. Verifieer dat factuur in Exact verschijnt, statussen kloppen, verschil-geval een hold krijgt.

- [ ] **Stap 8: Commit**

```bash
git add invoice_from_delivery.py tests/test_invoice_from_delivery.py .github/workflows/invoice-delivery.yml
git commit -m "feat: facturatie op basis van dagelijks leverancier-Excel"
```

---

## Task 9: Acceptance & oplevering

- [ ] **Stap 1: Happy-path demo met Patrick** — stuur testmail, doorloop intake → goedkeuren → order → delivery → invoice.
- [ ] **Stap 2: Edge-case demo** — onbekende klant, onvolledige mail, transportschade-verschil.
- [ ] **Stap 3: Runbook schrijven** in `docs/runbook.md`: hoe opnieuw inloggen bij Exact, hoe een hold afhandelen, hoe mailbox-credentials roteren.
- [ ] **Stap 4: Schakel eerdere handmatige workflow uit** (na 1 week dubbel draaien).
- [ ] **Stap 5: Eindfactuur sturen (50%).**

---

## Antwoorden Patrick (2026-04-13)

1. **Mailbox:** `orders@earthwater.nl` is **Gmail** → gebruik Gmail API met OAuth (of app-password via IMAP als eenvoudigere route).
2. **Leverancier-terugkoppeling:** vermoedelijk via Exact zelf (DeliveryStatus op order). **Verifiëren na herinlog.**
3. **Leverancier-Excel:** komt per mail. Laten forwarden naar `orders@earthwater.nl`, dan kan mail-intake het detecteren (bv. op afzender/bijlage-naam) en doorsturen naar `invoice_from_delivery.py`.
4. **Testen:** nog **niet** live testen op Exact-productie. Live Exact-calls pas uitvoeren na expliciete go.

---

## Volgorde: wat kan NU (zonder Exact) vs NA HERINLOG

### ✅ Nu uitvoerbaar (geen live Exact-calls)
- **Task 1** — OAuth-logica (code + unit tests met mocks, zonder `python exact_auth.py`)
- **Task 2** — EDI-uitsluiting (pure data-filter + tests)
- **Task 3** — Dashboard consolidatie (UI refactor)
- **Task 4** — Gmail-intake + Supabase-migraties (met eigen Gmail-credentials zodra beschikbaar)
- **Task 5** — Order parser (offline fixtures in `voorbeelden/`)
- **Task 6 tot aan POST** — payload-builder + review-gate in dashboard (unit tests, geen POST)
- **Task 8 tot aan POST** — Excel-matcher + discrepancy-logica (pure functies, tests)

### ⏸ Wacht op herinlog + Patrick's go

| Stap | Reden |
|---|---|
| Task 1 stap 6 — eenmalige `python exact_auth.py` | Patrick moet inloggen in browser |
| Task 6 — echte SalesOrder POST met testmail | Live Exact nodig |
| Task 7 — delivery status sync live draaien + verifiëren hoe Delta Wijnen terugkoppelt | Live Exact + observatie |
| Task 8 — SalesInvoice creation + Send | Live Exact, na Patrick's go |
| Task 9 — acceptance demo + eindoplevering | Alles hierboven groen |

---

## Checklist: uitvoeren zodra weer ingelogd bij Exact

- [ ] **A. Patrick voert `python exact_auth.py` uit**, browser → login → redirect-URL plakken. Verifieer dat `exact_tokens.json` + Supabase `config` rij een `expires_at` bevatten.
- [ ] **B. Smoke-test refresh:** `python -c "from exact_auth import get_access_token; print(get_access_token()[:10])"` — moet token teruggeven zonder extra refresh-call (dankzij expiry-check uit Task 1).
- [ ] **C. `python sync_orders.py --dry-run`** — verifieer dat EDI-klanten er niet meer in zitten (Task 2).
- [ ] **D. `python auto_delivery.py --dry-run`** — verifieer dat het niet meer filtert op "Kantoor EARTH" maar op niet-EDI (Task 2).
- [ ] **E. Check 3 recente orders in Exact** — kijk hoe Delta Wijnen terugkoppelt: is het via `DeliveryStatus` op dezelfde order, of wordt er een nieuwe entity aangemaakt? Bevestigt aanname in Task 7.
- [ ] **F. Stuur testmail naar `orders@earthwater.nl`** met voorbeeld-PDF. Verifieer binnen 10 min:
  - Mail in Supabase `incoming_orders` (Task 4)
  - Parser vult `parsed_data` (Task 5)
  - Review-kaart zichtbaar in dashboard (Task 6)
- [ ] **G. Patrick keurt testmail goed in dashboard** — SalesOrder verschijnt in Exact testdivisie (of productie, met goedkeuring).
- [ ] **H. Forward één leverancier-Excel** naar `orders@earthwater.nl`, verifieer dat `invoice_from_delivery.py` het oppakt, factuur aanmaakt (nog NIET verstuurt — eerst hold/preview).
- [ ] **I. Stagnatie-alert testen** — zet een testorder handmatig op "verzonden", check of na simulated 5 dagen alert triggert.
- [ ] **J. 1 week parallel draaien** (handmatig + automatisch) — vergelijk uitkomsten dagelijks.
- [ ] **K. Handmatige workflow uitzetten** + eindfactuur 50% sturen.
