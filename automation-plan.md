# Automation-plan: van review-dashboard naar hands-off

Doel: Patrick raakt de intake-flow niet meer aan. Alles wat nu misgaat komt door
matching (klant/artikel niet in Exact terug te vinden) of door edge-cases in de
parser. Dit plan vervangt de live Exact-API-matching door een lokale katalogus
met fuzzy match + self-learning aliases. Daarna durven we auto-POST zonder
tussenkomst aan te zetten.

## Huidige pijn

- Elke order doet 2+ live OData-calls naar Exact om klant/artikel op te zoeken.
- `Name eq '...'` matched alleen exact; fuzzy-fallback is een simpele
  `substringof`. Klanten die in Exact net anders heten (B.V., spaties, typo)
  vallen stuk.
- Artikelcodes worden soms niet als code maar als vrije omschrijving
  aangeleverd — geen match → `needs_review`.
- Dashboard heeft geen manier om handmatig te corrigeren anders dan in Exact
  zelf iets aanpassen en retry.

## Architectuur

```
Exact Online ──(nightly sync)──► Supabase catalog
                                     │
                                     ├─ exact_accounts
                                     ├─ exact_items
                                     ├─ customer_aliases  ◄── self-learning
                                     └─ item_aliases      ◄── self-learning

Mail-intake → Claude parse → matcher.py (lokale katalogus + rapidfuzz + aliases)
                             │
                             ├─ hoge confidence ─► auto-POST naar Exact
                             ├─ middle          ─► ready_for_approval (review)
                             └─ laag / mismatch ─► needs_review + dashboard-dropdown
```

## Stappen

### 1. Katalogus in Supabase (PR 1 — deze iteratie)

- Migratie `003_catalog.sql`: tabellen `exact_accounts`, `exact_items`,
  `customer_aliases`, `item_aliases`. Geen pg_trgm nodig; Python doet het werk.
- `src/catalog_sync.py`: haalt alle actieve Accounts en Items op via
  bestaande `ExactClient.get` (paginerend), normaliseert namen en upsert
  in Supabase. Batched zodat het duizenden rijen aankan.
- GitHub workflow `catalog-sync.yml`: dagelijks 05:00 UTC + `workflow_dispatch`.

### 2. Nieuwe matcher (PR 1)

- `src/matcher.py` met drie lagen:
  1. **Alias-hit** — als dezelfde klantnaam / artikel-omschrijving al eens
     is vastgelegd → directe match met confidence 1.0.
  2. **Exact (normalized)** — lowercase, strip "B.V./N.V./V.O.F./&", strip
     punctuatie/whitespace → exact match op `name_normalized` /
     `code` / `description_normalized`.
  3. **Fuzzy** — rapidfuzz `WRatio` met threshold 85 (klanten) / 80 (items).
     Voor items ook altijd code-prefix check (zodat `EW9208` -> `EW9208-NL` matcht).
- `order_creator.py`: `match_customer` en `match_items` vervangen door
  `matcher.match_customer(sb, name)` en `matcher.match_items(sb, lines)`.
  Exact-API blijft alleen nog voor de POST van de uiteindelijke order.

### 3. Self-learning aliases (PR 2)

- Dashboard: op `needs_review` + `ready_for_approval` detailpagina dropdowns
  "vervang klant" / "vervang artikel per regel". Bij klik:
  - Alias vastleggen in `customer_aliases` / `item_aliases` met `source='manual'`.
  - `parsed_data.matched_customer` / `matched_items` overschrijven,
    `salesorder_payload` herberekenen, status naar `ready_for_approval`.
- Resultaat: elke keer dat Patrick iets corrigeert, leert het systeem
  automatisch.

### 4. Auto-POST drempel (PR 3)

- Config-vlag `auto_post_min_confidence` (default 0.95) in `config` tabel.
- In `process_pipeline.py`: als `match_confidence >= drempel` en er is een
  bekende alias-hit voor álle regels → direct POST, sla `ready_for_approval`
  en reviewstap over. Status gaat van `parsed` → `created`.
- Patrick ziet deze orders alleen nog als overzicht ("14 vandaag automatisch
  doorgezet"), grijpt alleen in bij afwijkingen.

### 5. Edge cases (PR 4, doorlopend)

- Klant niet in Exact → alert-mail naar Patrick (nieuwe relatie aanmaken),
  status `needs_review` met reden.
- Artikel niet in Exact → idem.
- PDF onleesbaar (OCR nodig) → fallback Claude met vision.
- Leverdatum in verleden / ontbreekt → default = vandaag + 3 werkdagen.

## Volgorde van uitrol

1. **Nu (deze commit):** stap 1 + 2 — katalogus-sync + nieuwe matcher achter
   de schermen, review-flow blijft. Geen gedragsverandering voor Patrick,
   alleen betere match-accuracy.
2. **+2 dagen:** stap 3 — dashboard leert van handmatige correcties.
3. **+1 week draaien op review-modus, dan:** stap 4 — auto-POST aanzetten
   voor klant/artikel-combinaties met bewezen aliases.
4. **Doorlopend:** stap 5 — edge-cases vangen, alert-flow verfijnen.

## Succesmaat

- Week 1: >80% van nieuwe mails komt als `ready_for_approval` binnen
  (i.p.v. `needs_review`).
- Week 3: >90% auto-POST zonder handmatige actie.
- Maand 2: Patrick logt alleen in het dashboard bij uitzondering.
