# Python modules — Earth Water

Overzicht van alle `.py` bestanden in [`src/`](../src/). Tests draaien via een `conftest.py` in de repo-root die `src/` aan `sys.path` toevoegt; `run_sync.bat` en de GitHub Actions workflows (`sync-orders.yml`, `keepalive.yml`) gebruiken `src/` als working-directory.

## Runtime / production

| Bestand | Rol | Korte uitleg |
|---|---|---|
| [sync_incremental.py](../src/sync_incremental.py) | **Entry-point** (elke 15 min via GitHub Actions + lokaal via `run_sync.bat`) | Haalt orders op die sinds de laatste sync zijn gewijzigd, her-checkt niet-finale orders, en upsert naar Supabase. Bewaart laatste-sync-timestamp in Supabase `config` (met lokale file-fallback). |
| [sync_orders.py](../src/sync_orders.py) | Full sync (eenmalig / backfill) | Synchroniseert alle 2026-orders van Exact Online naar Supabase. Exporteert ook `transform_order`, `transform_order_line`, `ORDER_FIELDS`, `LINE_FIELDS` die door `sync_incremental.py` hergebruikt worden. |
| [auto_delivery.py](../src/auto_delivery.py) | **Fase 1 — Semso quick win** | Maakt automatisch `GoodsDeliveries` aan in Exact voor open orders (excl. EDI-klanten). Dit is de handmatige "op verzenden zetten"-stap die Patrick nu nog handmatig doet. |
| [exact_client.py](../src/exact_client.py) | Exact Online API-client | Herbruikbare wrapper rond de REST API met automatische token-refresh, paginatie en retry. Tokens staan in Supabase `config` zodat GitHub Actions stateless kan draaien (lokale file-fallback). |
| [exact_auth.py](../src/exact_auth.py) | OAuth2 bootstrap (eenmalig) | Interactieve flow om de eerste access/refresh token te verkrijgen: opent browser → gebruiker plakt code → tokens worden opgeslagen. Daarna neemt `exact_client.py` het over. |
| [alerts.py](../src/alerts.py) | E-mail alerts | Verstuurt alert-mails bij kritieke syncfouten via SMTP (env-vars `SMTP_HOST/PORT/USER/PASS/FROM`, `ALERT_EMAIL`). Faalt stil als SMTP niet geconfigureerd is (lokale dev). |
| [edi_exclusions.py](../src/edi_exclusions.py) | EDI-klantfilter | Laadt `edi_customers.txt` en biedt `is_edi_customer(name)` zodat EDI-klanten uit alle automatisering worden gefilterd (zij lopen al via hun eigen EDI-pad). |

## Fase 2 — mail/PDF intake (in ontwikkeling)

| Bestand | Rol | Korte uitleg |
|---|---|---|
| [mail_intake.py](../src/mail_intake.py) | Gmail → Supabase | IMAP-poller voor `orders@earthwater.nl`: slaat nieuwe mails op in `incoming_orders` en upload bijlagen naar storage-bucket `order-attachments`. Parsing gebeurt in `order_parser.py`. |
| [order_parser.py](../src/order_parser.py) | Claude AI parser | Extraheert gestructureerde orderdata (klant, producten, referentie, leverdatum, adres) uit e-mailtekst en/of PDF-bijlagen via de Anthropic API met prompt-caching op de system-prompt. |
| [order_creator.py](../src/order_creator.py) | SalesOrder-builder + matcher | Matcht klant en artikelen tegen Exact, bouwt de SalesOrder-payload en bepaalt confidence. Doet **geen** live POST — zet orders op `ready_for_approval` zodat Patrick via het review-dashboard kan goedkeuren. |

## Tests

Alle tests staan in [tests/](../tests/) en zijn 1-op-1 gekoppeld aan de modules hierboven:

- `test_exact_client.py`, `test_exact_auth.py`
- `test_sync_orders.py`, `test_sync_incremental.py`
- `test_auto_delivery.py`
- `test_edi_exclusions.py`
- `test_mail_intake.py`
- `test_order_parser.py`, `test_order_creator.py`

Draaien: `pytest` vanuit de repo-root.

## Afhankelijkheidsgraaf (high-level)

```
sync_incremental.py ──> exact_client.py ──> alerts.py
        │                    │
        ├──> sync_orders.py ──┘
        └──> edi_exclusions.py

auto_delivery.py   ──> exact_client.py, edi_exclusions.py

mail_intake.py     ──> (Supabase, IMAP)
order_parser.py    ──> (Anthropic API)
order_creator.py   ──> (Supabase, Exact matching)

exact_auth.py      ──> (eenmalige OAuth bootstrap, standalone)
```
