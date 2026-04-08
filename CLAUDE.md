# Earth Water - Orderverwerking Automatisering

## Klant
- **Bedrijf:** Earth Concepts B.V. (handelsnaam: Earth Water)
- **Contact:** Patrick de Nekker
- **Systeem:** Exact Online (administratie 746)
- **Website:** earthwater.nl
- **Wat doen ze:** Premium watermerk sinds 2007, doneert 100% nettowinst aan schoon drinkwaterprojecten

## Project
Automatisering van orderverwerking. Bestellingen die nu handmatig worden verwerkt (mail, PDF, Semso) automatisch laten doorlopen naar Exact Online en de logistieke partner.

**Projectprijs:** € 4.500 excl. BTW (€ 5.445 incl.)
**Uurtarief:** € 70 excl. BTW
**Doorlooptijd:** 3-4 weken
**Facturatie:** 25% bij aanvang -> 25% na fase 1+2 -> 50% na eindoplevering

## Huidige situatie

Er zijn 3 typen bestellingen:

| Type | Bron | Status | Volume |
|---|---|---|---|
| EDI | Automatisch | Loopt al, geen actie nodig | - |
| Semso | Semso platform | Staat in Exact, moet handmatig doorgestuurd naar logistiek | Onbekend |
| Mail/PDF | E-mail | Volledig handmatig invoeren in Exact | ~30/week |

Na invoer in Exact volgt voor alle orders hetzelfde traject:
**Order in Exact -> verzenden naar logistieke partner -> 2 dagen later factureren**

## Fases

### Fase 1: Semso orders automatisch doorsturen (quick win) - 8 uur
- Semso orders staan al in Exact maar moeten handmatig op "verzenden" gezet worden
- Automatische trigger bouwen: nieuwe Semso order in Exact -> direct doorsturen naar logistieke partner
- **Stack:** n8n + Exact Online API
- **Onbekend:** Hoe werkt de Semso-Exact koppeling precies? Uitzoeken bij start.

### Fase 2: Mail/PDF bestellingen automatisch verwerken (hoofdklus) - 50 uur

**2a. E-mail intake** (3-4 uur)
- Aparte mailbox inrichten (bijv. orders@earthwater.nl)
- n8n workflow: monitor mailbox, pak bijlagen (PDF) en mailtekst op

**2b. AI document parsing** (10-14 uur)
- Claude API om uit elke mail/PDF bestelgegevens te extraheren:
  - Product(en) + artikelcode
  - Aantal (dozen/cases)
  - Prijs
  - Referentienummer (PO-nummer klant)
  - Leverdatum
  - Afleveradres
- PDF's variteren per klant (zie voorbeeld: Minor Hotels PO in uitvragen map)
- Validatielaag: check of data compleet en logisch is

**2c. Exact Online koppeling** (12-16 uur)
- Klantenmatching: afzender/bedrijfsnaam -> bestaande relatie in Exact
- Productmatching: bestelde producten -> artikelen in Exact
- Verkooporder aanmaken via Exact Online REST API
- Automatisch doorsturen naar logistieke partner

**2d. Review-dashboard** (6-8 uur)
- Simpel overzicht waar Patrick geparsede orders kan goedkeuren voor ze in Exact gaan
- In het begin belangrijk voor vertrouwen, kan later weg als systeem betrouwbaar is

**2e. Testen & finetunen** (6-8 uur)
- Testen met echte orders van verschillende klanten
- Edge cases: onvolledige mails, nieuwe klanten, afwijkende formats

### Fase 3: Facturatie automatiseren - 6 uur
- Scheduled job in n8n: openstaande orders checken, na 2 dagen automatisch factureren
- Mogelijk loopt dit al voor online orders (dan is het 0 uur)

## Tech Stack
- **n8n** - workflow automation (email monitoring, triggers, scheduling)
- **Claude API** - AI parsing van mails/PDF's
- **Exact Online REST API** - orders, klanten, facturen
- **Supabase** - review-dashboard + logging

## Nodig om te starten
- [ ] Toegang tot Exact Online API (of testomgeving)
- [ ] 5-10 voorbeeld mails/PDF's van verschillende klanten
- [ ] Producten/artikelcodes lijst uit Exact
- [ ] Klantenlijst uit Exact (voor matching)

## Risico's
- **Semso integratie:** Onbekend hoe dit precies werkt, kan meevallen of tegenvallen
- **PDF variatie:** Sommige klanten sturen mogelijk handgeschreven of slecht geformatteerde orders
- **Productmatching:** Als klanten andere productnamen gebruiken dan in Exact moet er een vertaaltabel komen

## Doorlopende kosten na oplevering
| Onderdeel | Kosten/maand |
|---|---|
| n8n (cloud of self-hosted) | € 0-25 |
| Claude API (~120 orders/maand) | € 5-15 |
| Exact Online API | Inbegrepen in hun abonnement |
| **Totaal** | **€ 5-40** |

## Context bestanden
- `voorstel Earth concepts bv.pdf` - het verstuurde voorstel
- Originele uitvraag en reactie: `../Freelance uitvragen/uitvragen/2026-03-29_watermerk-exact-online.md`
- Intern projectplan: `../Freelance uitvragen/uitvragen/2026-03-31_watermerk-projectplan.md`
- Follow-up mail + antwoorden: `../Freelance uitvragen/uitvragen/2026-03-30_watermerk-followup-mail.md`
- Voorbeeld PDF bestelling: Minor Hotels PO (inkoop order 4600122152)
