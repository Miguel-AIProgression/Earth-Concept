# Fase 1: Automatisch GoodsDelivery aanmaken voor Semso/EDI orders

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatisch GoodsDeliveries aanmaken in Exact Online voor Semso/EDI orders (creator "Kantoor EARTH") met DeliveryStatus Open (12), zodat ze doorgestuurd worden naar de logistieke partner zonder handmatige actie.

**Architecture:** Python script `auto_delivery.py` dat via de bestaande `ExactClient` openstaande Kantoor EARTH orders detecteert, per order de regels ophaalt, en een GoodsDelivery POST doet. Draait als scheduled job (cron/n8n). Logging naar bestand + console. Dry-run modus voor veilig testen.

**Tech Stack:** Python, ExactClient (bestaand), Exact Online REST API

---

## Huidige staat

| Component | Status | Bestand |
|---|---|---|
| ExactClient (auth, GET, POST, paginatie, retry) | KLAAR | `exact_client.py` |
| OAuth2 flow + tokens | KLAAR | `exact_auth.py`, `exact_tokens.json` |
| Order sync naar Supabase | KLAAR | `sync_orders.py` |
| Dashboard (orders overzicht) | KLAAR | `dashboard/` |
| **auto_delivery.py** | **NOG TE BOUWEN** | - |

## Context voor de uitvoerder

### Hoe Exact Online orders werken
- **SalesOrder** heeft een `DeliveryStatus`: Open (12), Gedeeltelijk (20), Volledig (21)
- **GoodsDelivery** = bevestiging dat goederen zijn verzonden. Aanmaken verandert DeliveryStatus van de order.
- Creator `Kantoor EARTH` = Semso/EDI orders (automatisch aangemaakt)
- Creator `Patrick de Nekker` = handmatig ingevoerd
- Divisie: **2050702** (EARTH Concepts)

### API details
- Base URL: `https://start.exactonline.nl/api/v1/2050702`
- Auth: OAuth2 Bearer token (automatisch via `ExactClient`)
- GoodsDelivery aanmaken: `POST /salesorder/GoodsDeliveries` met `GoodsDeliveryLines` die verwijzen naar `SalesOrderLineID`

### ExactClient interface (bestaand)
```python
from exact_client import ExactClient
client = ExactClient()
results = client.get("/salesorder/SalesOrders", params={...})  # retourneert list
response = client.post("/salesorder/GoodsDeliveries", payload)  # retourneert dict
```

---

## File Structure

| File | Verantwoordelijkheid |
|---|---|
| `exact_client.py` | BESTAAND — API client, niet aanpassen |
| `auto_delivery.py` | NIEUW — detecteer open orders, maak GoodsDeliveries |
| `tests/test_auto_delivery.py` | NIEUW — unit tests |

---

## Task 1: Open Semso/EDI orders detecteren

**Files:**
- Create: `auto_delivery.py`
- Create: `tests/test_auto_delivery.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_auto_delivery.py
from unittest.mock import MagicMock
from auto_delivery import get_open_kantoor_orders

def test_get_open_kantoor_orders_filters_correctly():
    """Retourneert alleen orders van Kantoor EARTH met DeliveryStatus 12."""
    mock_client = MagicMock()
    mock_client.get.return_value = [
        {"OrderNumber": 9527, "CreatorFullName": "Kantoor EARTH", "DeliveryStatus": 12},
        {"OrderNumber": 9545, "CreatorFullName": "Patrick de Nekker", "DeliveryStatus": 12},
        {"OrderNumber": 9537, "CreatorFullName": "Kantoor EARTH", "DeliveryStatus": 21},
    ]

    result = get_open_kantoor_orders(mock_client)

    assert len(result) == 1
    assert result[0]["OrderNumber"] == 9527


def test_get_open_kantoor_orders_empty():
    """Geen orders -> lege lijst."""
    mock_client = MagicMock()
    mock_client.get.return_value = []

    result = get_open_kantoor_orders(mock_client)
    assert result == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_auto_delivery.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'auto_delivery'`

- [ ] **Step 3: Implement get_open_kantoor_orders**

```python
# auto_delivery.py
"""Automatisch GoodsDeliveries aanmaken voor Kantoor EARTH (Semso/EDI) orders."""

import sys
import logging

from exact_client import ExactClient

CREATOR_KANTOOR = "Kantoor EARTH"

log = logging.getLogger(__name__)


def get_open_kantoor_orders(client):
    """Haal alle open orders op die zijn aangemaakt door Kantoor EARTH."""
    orders = client.get("/salesorder/SalesOrders", params={
        "$filter": "DeliveryStatus eq 12",
        "$select": "OrderID,OrderNumber,OrderDate,DeliveryStatus,"
                   "CreatorFullName,OrderedByName,Description,YourRef,DeliveryDate",
        "$orderby": "OrderDate desc",
    })
    return [o for o in orders if o.get("CreatorFullName") == CREATOR_KANTOOR]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_auto_delivery.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add auto_delivery.py tests/test_auto_delivery.py
git commit -m "feat: detect open Kantoor EARTH orders"
```

---

## Task 2: Orderregels ophalen (onafgeleverde regels)

**Files:**
- Modify: `auto_delivery.py`
- Modify: `tests/test_auto_delivery.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_auto_delivery.py (toevoegen)
from auto_delivery import get_undelivered_lines

def test_get_undelivered_lines_filters_delivered():
    mock_client = MagicMock()
    mock_client.get.return_value = [
        {"ID": "line-1", "ItemCode": "EW72306", "Quantity": 84, "QuantityDelivered": 0},
        {"ID": "line-2", "ItemCode": "EW72310", "Quantity": 50, "QuantityDelivered": 50},
    ]

    result = get_undelivered_lines(mock_client, "order-id-123")

    assert len(result) == 1
    assert result[0]["ID"] == "line-1"


def test_get_undelivered_lines_partial_delivery():
    """Gedeeltelijk afgeleverde regels moeten wel mee."""
    mock_client = MagicMock()
    mock_client.get.return_value = [
        {"ID": "line-1", "ItemCode": "EW72306", "Quantity": 84, "QuantityDelivered": 40},
    ]

    result = get_undelivered_lines(mock_client, "order-id-123")
    assert len(result) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_auto_delivery.py::test_get_undelivered_lines_filters_delivered -v`
Expected: FAIL

- [ ] **Step 3: Implement get_undelivered_lines**

```python
# auto_delivery.py (toevoegen)

def get_undelivered_lines(client, order_id):
    """Haal orderregels op die nog niet (volledig) afgeleverd zijn."""
    lines = client.get("/salesorder/SalesOrderLines", params={
        "$filter": f"OrderID eq guid'{order_id}'",
        "$select": "ID,OrderID,OrderNumber,ItemCode,ItemDescription,"
                   "Quantity,QuantityDelivered,DeliveryDate",
    })
    return [l for l in lines if l.get("Quantity", 0) > l.get("QuantityDelivered", 0)]
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_auto_delivery.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add auto_delivery.py tests/test_auto_delivery.py
git commit -m "feat: get undelivered order lines"
```

---

## Task 3: GoodsDelivery aanmaken

**Files:**
- Modify: `auto_delivery.py`
- Modify: `tests/test_auto_delivery.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_auto_delivery.py (toevoegen)
from auto_delivery import create_goods_delivery

def test_create_goods_delivery_payload():
    mock_client = MagicMock()
    mock_client.post.return_value = {"d": {"EntryID": "gd-1", "DeliveryNumber": 7820}}

    order = {
        "OrderID": "order-123",
        "OrderNumber": 9527,
        "Description": "4600130365",
        "DeliveryDate": "/Date(1775692800000)/",
    }
    lines = [
        {"ID": "line-1", "ItemCode": "EW72306", "Quantity": 84, "QuantityDelivered": 0},
        {"ID": "line-2", "ItemCode": "EW72310", "Quantity": 50, "QuantityDelivered": 20},
    ]

    result = create_goods_delivery(mock_client, order, lines)

    call_args = mock_client.post.call_args
    assert call_args[0][0] == "/salesorder/GoodsDeliveries"

    payload = call_args[0][1]
    assert len(payload["GoodsDeliveryLines"]) == 2
    assert payload["GoodsDeliveryLines"][0]["SalesOrderLineID"] == "line-1"
    assert payload["GoodsDeliveryLines"][0]["QuantityDelivered"] == 84
    assert payload["GoodsDeliveryLines"][1]["QuantityDelivered"] == 30  # 50 - 20


def test_create_goods_delivery_empty_lines_raises():
    mock_client = MagicMock()
    import pytest
    with pytest.raises(ValueError):
        create_goods_delivery(mock_client, {"OrderNumber": 1}, [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_auto_delivery.py::test_create_goods_delivery_payload -v`
Expected: FAIL

- [ ] **Step 3: Implement create_goods_delivery**

```python
# auto_delivery.py (toevoegen)

def create_goods_delivery(client, order, lines):
    """Maak een GoodsDelivery aan voor een order met de gegeven regels."""
    if not lines:
        raise ValueError(f"Geen regels voor order #{order.get('OrderNumber')}")

    delivery_lines = []
    for line in lines:
        remaining = line["Quantity"] - line.get("QuantityDelivered", 0)
        delivery_lines.append({
            "SalesOrderLineID": line["ID"],
            "QuantityDelivered": remaining,
        })

    payload = {
        "Description": order.get("Description", ""),
        "DeliveryDate": order.get("DeliveryDate"),
        "GoodsDeliveryLines": delivery_lines,
    }

    return client.post("/salesorder/GoodsDeliveries", payload)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_auto_delivery.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add auto_delivery.py tests/test_auto_delivery.py
git commit -m "feat: create GoodsDelivery via Exact API"
```

---

## Task 4: Hoofdflow + CLI

**Files:**
- Modify: `auto_delivery.py`
- Modify: `tests/test_auto_delivery.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_auto_delivery.py (toevoegen)
from auto_delivery import process_open_orders

def test_process_open_orders_end_to_end():
    mock_client = MagicMock()
    mock_client.get.side_effect = [
        # Call 1: open orders
        [{"OrderID": "o1", "OrderNumber": 9556, "CreatorFullName": "Kantoor EARTH",
          "DeliveryStatus": 12, "Description": "2026.01/153.032",
          "DeliveryDate": "/Date(1775692800000)/", "OrderedByName": "Kreko B.V."}],
        # Call 2: order lines voor o1
        [{"ID": "l1", "ItemCode": "EW72306", "Quantity": 84, "QuantityDelivered": 0}],
    ]
    mock_client.post.return_value = {"d": {"EntryID": "gd-1", "DeliveryNumber": 7820}}

    results = process_open_orders(mock_client)

    assert len(results) == 1
    assert results[0]["order_number"] == 9556
    assert results[0]["success"] is True
    assert results[0]["delivery_number"] == 7820


def test_process_open_orders_skips_no_lines():
    mock_client = MagicMock()
    mock_client.get.side_effect = [
        [{"OrderID": "o1", "OrderNumber": 9999, "CreatorFullName": "Kantoor EARTH",
          "DeliveryStatus": 12, "Description": "test", "DeliveryDate": None,
          "OrderedByName": "Test B.V."}],
        [],  # geen openstaande regels
    ]

    results = process_open_orders(mock_client)
    assert len(results) == 0  # geen delivery aangemaakt


def test_process_open_orders_handles_api_error():
    mock_client = MagicMock()
    mock_client.get.side_effect = [
        [{"OrderID": "o1", "OrderNumber": 9999, "CreatorFullName": "Kantoor EARTH",
          "DeliveryStatus": 12, "Description": "test", "DeliveryDate": None,
          "OrderedByName": "Test B.V."}],
        [{"ID": "l1", "ItemCode": "EW72306", "Quantity": 10, "QuantityDelivered": 0}],
    ]
    mock_client.post.side_effect = Exception("API error 500")

    results = process_open_orders(mock_client)

    assert len(results) == 1
    assert results[0]["success"] is False
    assert "API error" in results[0]["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_auto_delivery.py::test_process_open_orders_end_to_end -v`
Expected: FAIL

- [ ] **Step 3: Implement process_open_orders + __main__**

```python
# auto_delivery.py (toevoegen, bovenaan logging toevoegen)

def process_open_orders(client, dry_run=False):
    """Verwerk alle open Kantoor EARTH orders."""
    orders = get_open_kantoor_orders(client)
    log.info(f"Gevonden: {len(orders)} open Kantoor EARTH orders")
    if dry_run:
        log.info("DRY RUN — geen deliveries worden aangemaakt")

    results = []
    for order in orders:
        order_num = order["OrderNumber"]
        customer = order.get("OrderedByName", "")
        try:
            lines = get_undelivered_lines(client, order["OrderID"])
            if not lines:
                log.info(f"  #{order_num} ({customer}): geen openstaande regels, skip")
                continue

            line_summary = ", ".join(
                f"{l['ItemCode']} x{l['Quantity'] - l.get('QuantityDelivered', 0):.0f}"
                for l in lines
            )
            log.info(f"  #{order_num} ({customer}): {line_summary}")

            if dry_run:
                results.append({
                    "order_number": order_num,
                    "customer": customer,
                    "success": True,
                    "dry_run": True,
                })
                continue

            response = create_goods_delivery(client, order, lines)
            delivery_data = response.get("d", response)
            delivery_num = delivery_data.get("DeliveryNumber", "?")
            log.info(f"  #{order_num}: GoodsDelivery #{delivery_num} aangemaakt")

            results.append({
                "order_number": order_num,
                "customer": customer,
                "success": True,
                "delivery_number": delivery_num,
            })
        except Exception as e:
            log.error(f"  #{order_num} ({customer}): FOUT — {e}")
            results.append({
                "order_number": order_num,
                "customer": customer,
                "success": False,
                "error": str(e),
            })

    return results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler("auto_delivery.log"),
            logging.StreamHandler(),
        ],
    )
    dry_run = "--dry-run" in sys.argv
    client = ExactClient()
    mode = "(DRY RUN) " if dry_run else ""
    log.info(f"=== Auto Delivery {mode}gestart ===")

    results = process_open_orders(client, dry_run=dry_run)

    success = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]
    log.info(f"Klaar: {len(success)} gelukt, {len(failed)} mislukt")
```

- [ ] **Step 4: Run all tests**

Run: `python -m pytest tests/test_auto_delivery.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add auto_delivery.py tests/test_auto_delivery.py
git commit -m "feat: main flow with dry-run, logging, and error handling"
```

---

## Task 5: Dry-run test tegen live Exact Online

**HANDMATIG — geen code te schrijven, alleen uitvoeren en verifi\u00ebren.**

- [ ] **Step 1: Draai dry-run**

Run: `python auto_delivery.py --dry-run`

Expected: lijst van open Kantoor EARTH orders met producten. Controleer:
- Zijn dit inderdaad Semso/EDI orders?
- Staan er orders bij die NIET doorgestuurd moeten worden?
- Klopt het aantal orders met wat je in het dashboard ziet bij filter "Semso/EDI" + status "Open"?

- [ ] **Step 2: Documenteer bevindingen**

Noteer in een comment of chat:
- Hoeveel orders gevonden
- Eventuele verrassingen (orders die er niet horen, ontbrekende orders)

---

## Task 6: Live test met 1 order

**BELANGRIJK: Overleg met Patrick voor je dit doet.**

- [ ] **Step 1: Kies een testorder**

Kies een order die sowieso doorgestuurd moet worden. Uit het dashboard (screenshot) zijn kandidaten:
- #9556 Kreko B.V. (Semso/EDI, Levering: Volledig — deze is al gedaan?)
- #9554 Hansen Dranken B.V. (Semso/EDI, Open)
- #9548 VHC ActiFood B.V. (Semso/EDI, Volledig — al gedaan?)

Kies een order met status "Open" bij levering.

- [ ] **Step 2: Test met die ene order**

```python
from exact_client import ExactClient
from auto_delivery import get_undelivered_lines, create_goods_delivery

client = ExactClient()

# Haal specifieke order op (vul ordernummer in)
orders = client.get("/salesorder/SalesOrders", params={
    "$filter": "OrderNumber eq 9554",
    "$select": "OrderID,OrderNumber,Description,DeliveryDate,OrderedByName"
})
order = orders[0]
lines = get_undelivered_lines(client, order["OrderID"])

print(f"Order: #{order['OrderNumber']} - {order['OrderedByName']}")
for l in lines:
    print(f"  {l['ItemCode']}: {l['Quantity'] - l.get('QuantityDelivered', 0):.0f}")

# Uncomment om delivery aan te maken:
# result = create_goods_delivery(client, order, lines)
# print(f"GoodsDelivery aangemaakt: {result}")
```

- [ ] **Step 3: Verifieer in Exact Online**

Check:
1. GoodsDelivery is aangemaakt
2. Order DeliveryStatus is veranderd naar "Volledig" (21)
3. Logistieke partner ontvangt de order

- [ ] **Step 4: Commit**

```bash
git commit --allow-empty -m "test: verified live GoodsDelivery for order #XXXX"
```

---

## Task 7: Volledige live run + scheduling

- [ ] **Step 1: Draai alle open orders**

Run: `python auto_delivery.py`

Controleer `auto_delivery.log` op fouten.

- [ ] **Step 2: Sync dashboard**

Run: `python sync_orders.py`

Controleer in het dashboard dat de delivery statussen zijn bijgewerkt.

- [ ] **Step 3: Scheduling opzetten**

Optie A — **n8n** (als n8n al draait):
- Maak een workflow met een Schedule trigger (bijv. elke 30 min)
- Execute Command node: `python /pad/naar/auto_delivery.py`

Optie B — **Windows Task Scheduler** (simpeler voor nu):
```bash
# Maak een .bat bestand
echo "cd /d C:\Users\migue\Documents\Earth water && python auto_delivery.py" > run_auto_delivery.bat
```
Dan via Task Scheduler elke 30 minuten laten draaien.

Optie C — **Cron** (als WSL/Linux):
```bash
*/30 * * * * cd /path/to/project && python auto_delivery.py >> auto_delivery.log 2>&1
```

- [ ] **Step 4: Commit**

```bash
git add auto_delivery.py .gitignore
git commit -m "feat: fase 1 complete - auto GoodsDelivery for Semso/EDI orders"
```

---

## Openstaande vragen voor Patrick

Voordat we live gaan, moet Patrick bevestigen:

1. **Klopt het dat "Kantoor EARTH" als creator = Semso/EDI orders?** Of zijn er ook andere orders met die creator?
2. **Is een GoodsDelivery aanmaken voldoende om door te sturen naar logistiek?** Of is er nog een extra stap (e-mail, EDI-bericht)?
3. **Moeten ALLE open Kantoor EARTH orders direct door?** Of zijn er orders die bewust moeten wachten?
4. **Hoe vaak moet dit draaien?** Elke 15 min / 30 min / uur / dag?
5. **Zijn er orders met status "Gedeeltelijk" (20) die ook verwerkt moeten worden?**
