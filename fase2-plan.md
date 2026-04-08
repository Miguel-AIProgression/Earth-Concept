# Fase 2: Mail/PDF bestellingen automatisch verwerken

## Overzicht
Bestellingen die via e-mail/PDF binnenkomen automatisch verwerken naar Exact Online.

## Flow
```
Gmail (nieuwe mail)
  → Extract mail + bijlagen
  → Claude API (parse bestelgegevens)
  → Match klant & producten in Exact Online
  → Review dashboard (Patrick keurt goed)
  → Verkooporder aanmaken in Exact Online
  → Doorsturen naar logistiek
```

## Stappen

### Stap 2a: Gmail intake (3-4 uur)
- IMAP-verbinding met orders-mailbox (bijv. orders@earthwater.nl)
- Nieuwe mails ophalen + bijlagen extraheren (PDF's)
- Verwerkte mails markeren zodat ze niet dubbel verwerkt worden

**Benodigd:**
- [ ] Gmail app-wachtwoord (of OAuth2 credentials)
- [ ] Beslissing: aparte mailbox (orders@earthwater.nl) of bestaande?

### Stap 2b: AI document parsing (10-14 uur)
- Claude API om uit elke mail/PDF te extraheren:
  - Product(en) + artikelcode
  - Aantal (dozen/cases)
  - Prijs per eenheid
  - PO-nummer klant
  - Gewenste leverdatum
  - Afleveradres
  - Klant/bedrijfsnaam
- Validatielaag: check of data compleet en logisch is
- Twee formats ondersteunen:
  1. Gestructureerde PDF (zoals Radisson/GPP - tabel met codes)
  2. Vrije tekst in e-mail (zoals Anantara - lopende tekst)

**Benodigd:**
- [ ] Claude API key
- [ ] 5-10 voorbeeldmails van verschillende klanten (nu 2 stuks)

### Stap 2c: Exact Online koppeling (12-16 uur)
- Klantenmatching: afzender/bedrijfsnaam → bestaande relatie in Exact
- Productmatching: bestelde producten → artikelen in Exact
- Verkooporder aanmaken via Exact Online REST API
- Automatisch doorsturen naar logistieke partner

**Benodigd:**
- [ ] Exact Online API credentials (Client ID + Secret) — via Exact App Center
- [ ] Productlijst uit Exact (artikelcodes + namen)
- [ ] Klantenlijst uit Exact (bedrijfsnamen + relatiecodes)
- [ ] Werkende Fase 1 (Exact API koppeling staat dan al)

### Stap 2d: Review dashboard (6-8 uur)
- Overzicht waar Patrick geparsede orders kan bekijken en goedkeuren
- Order details: klant, producten, aantallen, leverdatum
- Knoppen: goedkeuren (→ naar Exact) of afwijzen (→ handmatig)
- In het begin belangrijk voor vertrouwen, kan later weg

**Benodigd:**
- [ ] Supabase project (database + hosting)

### Stap 2e: Testen & finetunen (6-8 uur)
- Testen met echte orders van verschillende klanten
- Edge cases: onvolledige mails, nieuwe klanten, afwijkende formats
- Parsing-nauwkeurigheid verbeteren op basis van resultaten

**Benodigd:**
- [ ] Toegang tot echte orders (of testomgeving)

## Voorbeelddata (al beschikbaar)

### Mail 1: Radisson Hotel Brussels (gestructureerde PDF)
- Klant: Radisson Hotel Brussels Centre Midi (BRUPM)
- PO: 2603240334
- Product: EW Radisson TT 50cl (EW9208), 90 dozen, €12,25/doos
- Totaal: €1.102,50
- Levering: Rue de Hollande 4, 1060 Brussels

### Mail 2: Anantara Grand Hotel Krasnapolsky (vrije tekst)
- Klant: Anantara Hotels (Minor Hotels)
- Order 1 (PO 4600130365): 96 dozen Still Tetra 33cl + 70 dozen Still 75cl, levering 7 april
- Order 2 (PO 4600130368): 140 dozen Still 75cl, levering 9 april

## Tech stack
- **Python** — core parsing & API logic
- **Claude API** — AI parsing van mails/PDF's
- **Exact Online REST API** — orders, klanten, facturen
- **Gmail IMAP** — mail monitoring
- **Supabase** — review dashboard + logging
- **n8n** — orchestratie (later, als alles los werkt)
