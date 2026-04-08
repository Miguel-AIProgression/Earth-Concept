# Order Dashboard: Supabase + Next.js

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Alle 2026 bestellingen uit Exact Online synchroniseren naar Supabase en weergeven in een Next.js dashboard met filters op bron (Semso/EDI vs handmatig), zodat Patrick het volledige orderproces kan inzien en valideren.

**Architecture:** Python sync-script haalt orders + orderregels uit Exact Online en upsert ze in Supabase. Next.js frontend (App Router) leest direct uit Supabase via de JS client. Geen auth nodig — intern tool. Deploy via Vercel.

**Tech Stack:** Supabase (PostgreSQL), Next.js 14 (App Router), Tailwind CSS, @supabase/supabase-js, Python (sync), requests, supabase-py

---

## Context

### Supabase project
- **Project ID:** `eqdossfutuairijssdng`
- **URL:** `https://eqdossfutuairijssdng.supabase.co`
- **Region:** eu-central-1
- **Status:** Actief, geen tabellen

### Exact Online
- **Divisie:** 2050702 (EARTH Concepts)
- **Auth:** OAuth2, tokens in `exact_tokens.json`
- **Bestaand:** `exact_auth.py` met werkende token refresh + API calls

### Orderbronnen
| Bron | Creator in Exact | Hoe herkennen |
|---|---|---|
| Semso/EDI | `Kantoor EARTH` | Automatisch aangemaakt |
| Handmatig | `Patrick de Nekker` | Patrick zet ze er zelf in |
| Mail (toekomst) | Nog niet actief | Komt in fase 2b |

### Orderstatus-flow
```
Order aangemaakt → GoodsDelivery (= naar logistiek) → Factuur (2 dagen later)
```
- `DeliveryStatus`: 12=Open, 20=Gedeeltelijk, 21=Volledig
- `InvoiceStatus`: zichtbaar per order (of factuur al is aangemaakt)

---

## File Structure

| File | Verantwoordelijkheid |
|---|---|
| `exact_client.py` | Herbruikbare Exact Online API client (refactor van `exact_auth.py`) |
| `sync_orders.py` | Sync script: Exact → Supabase (alle 2026 orders) |
| `dashboard/` | Next.js app (App Router) |
| `dashboard/src/app/page.tsx` | Orders overzicht met filters |
| `dashboard/src/app/orders/[id]/page.tsx` | Order detail met regels |
| `dashboard/src/lib/supabase.ts` | Supabase client configuratie |
| `dashboard/src/components/order-table.tsx` | Orders tabel component |
| `dashboard/src/components/order-filters.tsx` | Filter UI (bron, status) |
| `dashboard/src/components/status-badge.tsx` | Status badges |
| `tests/test_exact_client.py` | Tests voor API client |
| `tests/test_sync_orders.py` | Tests voor sync logica |

---

## Task 1: Database schema aanmaken

**Files:** Supabase migration (via MCP)

### Doel
Tabellen `orders` en `order_lines` aanmaken in Supabase.

- [ ] **Step 1: Maak de migration aan**

```sql
-- orders tabel
CREATE TABLE orders (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  exact_order_id TEXT UNIQUE NOT NULL,
  order_number INTEGER NOT NULL,
  order_date DATE,
  delivery_status INTEGER,
  delivery_status_description TEXT,
  invoice_status INTEGER,
  invoice_status_description TEXT,
  creator TEXT,
  source TEXT GENERATED ALWAYS AS (
    CASE
      WHEN creator = 'Kantoor EARTH' THEN 'semso_edi'
      ELSE 'manual'
    END
  ) STORED,
  customer_name TEXT,
  description TEXT,
  your_ref TEXT,
  delivery_date DATE,
  amount NUMERIC(12,2),
  synced_at TIMESTAMPTZ DEFAULT NOW(),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- order_lines tabel
CREATE TABLE order_lines (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  order_id UUID REFERENCES orders(id) ON DELETE CASCADE,
  exact_line_id TEXT UNIQUE NOT NULL,
  item_code TEXT,
  item_description TEXT,
  quantity NUMERIC(10,2),
  quantity_delivered NUMERIC(10,2) DEFAULT 0,
  unit_price NUMERIC(10,2),
  amount NUMERIC(12,2),
  delivery_date DATE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_orders_source ON orders(source);
CREATE INDEX idx_orders_order_date ON orders(order_date);
CREATE INDEX idx_orders_delivery_status ON orders(delivery_status);
CREATE INDEX idx_order_lines_order_id ON order_lines(order_id);

-- RLS uit (intern tool, geen auth)
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE order_lines ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow public read orders" ON orders FOR SELECT USING (true);
CREATE POLICY "Allow public read order_lines" ON order_lines FOR SELECT USING (true);
```

Run via: `mcp__claude_ai_Supabase__apply_migration`

- [ ] **Step 2: Verifieer tabellen**

Run via: `mcp__claude_ai_Supabase__list_tables` met verbose=true

- [ ] **Step 3: Commit migratieplan**

```bash
git add docs/superpowers/plans/2026-04-08-order-dashboard.md
git commit -m "docs: add order dashboard implementation plan"
```

---

## Task 2: ExactClient refactoren

**Files:**
- Create: `exact_client.py`
- Create: `tests/test_exact_client.py`
- Keep: `exact_auth.py` (voor initiële OAuth flow)

### Doel
Herbruikbare client met token refresh, GET/POST, en **paginatie** (Exact retourneert max 60 results per page).

- [ ] **Step 1: Write failing test voor token refresh**

```python
# tests/test_exact_client.py
from unittest.mock import patch, MagicMock
from exact_client import ExactClient

def test_refresh_token():
    client = ExactClient.__new__(ExactClient)
    client.client_id = "test_id"
    client.client_secret = "test_secret"
    client.token_file = "test_tokens.json"
    client.tokens = {"refresh_token": "old_refresh"}

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "access_token": "new_access",
        "refresh_token": "new_refresh",
    }

    with patch("requests.post", return_value=mock_resp):
        with patch("builtins.open", MagicMock()):
            with patch("json.dump"):
                token = client.refresh_token()

    assert token == "new_access"
```

- [ ] **Step 2: Run test — verwacht FAIL**

Run: `python -m pytest tests/test_exact_client.py -v`

- [ ] **Step 3: Write failing test voor paginatie**

```python
# tests/test_exact_client.py (toevoegen)
def test_get_paginates():
    """Client moet __next links volgen voor alle resultaten."""
    client = ExactClient.__new__(ExactClient)
    client.base_url = "https://start.exactonline.nl/api/v1/2050702"
    client._access_token = "test"
    client._token_expires_at = 9999999999

    page1 = MagicMock()
    page1.status_code = 200
    page1.json.return_value = {
        "d": {
            "results": [{"OrderNumber": 1}, {"OrderNumber": 2}],
            "__next": "https://start.exactonline.nl/api/v1/2050702/next-page",
        }
    }
    page2 = MagicMock()
    page2.status_code = 200
    page2.json.return_value = {
        "d": {
            "results": [{"OrderNumber": 3}],
        }
    }

    with patch("requests.get", side_effect=[page1, page2]):
        results = client.get("/salesorder/SalesOrders")

    assert len(results) == 3
    assert results[2]["OrderNumber"] == 3
```

- [ ] **Step 4: Implement ExactClient**

```python
# exact_client.py
"""Herbruikbare Exact Online API client met token refresh en paginatie."""

import json
import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()


class ExactClient:
    TOKEN_URL = "https://start.exactonline.nl/api/oauth2/token"

    def __init__(self, token_file="exact_tokens.json"):
        self.client_id = os.getenv("EXACT_CLIENT_ID")
        self.client_secret = os.getenv("EXACT_CLIENT_SECRET")
        self.division = os.getenv("EXACT_DIVISION")
        self.token_file = token_file
        self.tokens = self._load_tokens()
        self.base_url = f"https://start.exactonline.nl/api/v1/{self.division}"
        self._access_token = None
        self._token_expires_at = 0

    def _load_tokens(self):
        if os.path.exists(self.token_file):
            with open(self.token_file) as f:
                return json.load(f)
        return {}

    def _save_tokens(self, tokens):
        with open(self.token_file, "w") as f:
            json.dump(tokens, f, indent=2)
        self.tokens = tokens

    def refresh_token(self):
        r = requests.post(self.TOKEN_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": self.tokens["refresh_token"],
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        })
        r.raise_for_status()
        new_tokens = r.json()
        self._save_tokens(new_tokens)
        self._access_token = new_tokens["access_token"]
        self._token_expires_at = time.time() + new_tokens.get("expires_in", 600) - 60
        return self._access_token

    def _get_token(self):
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token
        return self.refresh_token()

    def _headers(self):
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def get(self, endpoint, params=None):
        """GET met automatische paginatie (Exact retourneert max 60 per page)."""
        url = f"{self.base_url}{endpoint}"
        all_results = []
        while url:
            r = requests.get(url, headers=self._headers(), params=params)
            r.raise_for_status()
            data = r.json()
            d = data.get("d", data)
            if isinstance(d, dict):
                all_results.extend(d.get("results", []))
                url = d.get("__next")
            else:
                all_results.extend(d if isinstance(d, list) else [])
                url = None
            params = None  # params zitten al in __next URL
        return all_results

    def post(self, endpoint, payload):
        url = f"{self.base_url}{endpoint}"
        r = requests.post(url, headers=self._headers(), json=payload)
        r.raise_for_status()
        return r.json()
```

- [ ] **Step 5: Run tests — verwacht PASS**

Run: `python -m pytest tests/test_exact_client.py -v`

- [ ] **Step 6: Commit**

```bash
git add exact_client.py tests/test_exact_client.py
git commit -m "feat: add ExactClient with pagination and token caching"
```

---

## Task 3: Sync script (Exact → Supabase)

**Files:**
- Create: `sync_orders.py`
- Create: `tests/test_sync_orders.py`

### Doel
Alle 2026 SalesOrders + regels ophalen uit Exact en upserten in Supabase.

- [ ] **Step 1: Voeg Supabase credentials toe aan .env**

```
# toevoegen aan .env
SUPABASE_URL=https://eqdossfutuairijssdng.supabase.co
SUPABASE_SERVICE_KEY=<ophalen uit Supabase dashboard → Settings → API → service_role key>
```

- [ ] **Step 2: Installeer dependencies**

```bash
pip install supabase python-dotenv requests
```

- [ ] **Step 3: Write failing test voor order transformatie**

```python
# tests/test_sync_orders.py
from sync_orders import transform_order, transform_order_line

def test_transform_order():
    raw = {
        "OrderID": "abc-123",
        "OrderNumber": 9527,
        "OrderDate": "/Date(1775692800000)/",
        "DeliveryStatus": 12,
        "DeliveryStatusDescription": "Open",
        "InvoiceStatus": 0,
        "InvoiceStatusDescription": "",
        "CreatorFullName": "Kantoor EARTH",
        "OrderedByName": "Grand Hotel Krasnapolsky",
        "Description": "PO 4600130365",
        "YourRef": "4600130365",
        "DeliveryDate": "/Date(1775952000000)/",
        "AmountDC": 1234.56,
    }
    result = transform_order(raw)

    assert result["exact_order_id"] == "abc-123"
    assert result["order_number"] == 9527
    assert result["creator"] == "Kantoor EARTH"
    assert result["amount"] == 1234.56
    assert result["order_date"] is not None  # parsed date


def test_transform_order_line():
    raw = {
        "ID": "line-1",
        "ItemCode": "EW72306",
        "ItemDescription": "Earth Water Still 75cl",
        "Quantity": 84.0,
        "QuantityDelivered": 0.0,
        "NetPrice": 12.25,
        "Amount": 1029.0,
        "DeliveryDate": "/Date(1775952000000)/",
    }
    result = transform_order_line(raw, order_id="order-uuid-123")

    assert result["exact_line_id"] == "line-1"
    assert result["item_code"] == "EW72306"
    assert result["quantity"] == 84.0
    assert result["order_id"] == "order-uuid-123"
```

- [ ] **Step 4: Run test — verwacht FAIL**

Run: `python -m pytest tests/test_sync_orders.py -v`

- [ ] **Step 5: Implement sync_orders.py**

```python
# sync_orders.py
"""Synchroniseer alle 2026 orders van Exact Online naar Supabase."""

import os
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client
from exact_client import ExactClient

load_dotenv()
log = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

ORDER_FIELDS = (
    "OrderID,OrderNumber,OrderDate,DeliveryStatus,DeliveryStatusDescription,"
    "InvoiceStatus,InvoiceStatusDescription,CreatorFullName,OrderedByName,"
    "Description,YourRef,DeliveryDate,AmountDC"
)

LINE_FIELDS = (
    "ID,OrderID,OrderNumber,ItemCode,ItemDescription,"
    "Quantity,QuantityDelivered,NetPrice,Amount,DeliveryDate"
)


def parse_odata_date(date_str):
    """Parse Exact Online OData date format '/Date(1234567890000)/'."""
    if not date_str:
        return None
    try:
        ms = int(date_str.replace("/Date(", "").replace(")/", ""))
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        return None


def transform_order(raw):
    return {
        "exact_order_id": raw["OrderID"],
        "order_number": raw["OrderNumber"],
        "order_date": parse_odata_date(raw.get("OrderDate")),
        "delivery_status": raw.get("DeliveryStatus"),
        "delivery_status_description": raw.get("DeliveryStatusDescription"),
        "invoice_status": raw.get("InvoiceStatus"),
        "invoice_status_description": raw.get("InvoiceStatusDescription"),
        "creator": raw.get("CreatorFullName"),
        "customer_name": raw.get("OrderedByName"),
        "description": raw.get("Description"),
        "your_ref": raw.get("YourRef"),
        "delivery_date": parse_odata_date(raw.get("DeliveryDate")),
        "amount": raw.get("AmountDC"),
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }


def transform_order_line(raw, order_id):
    return {
        "order_id": order_id,
        "exact_line_id": raw["ID"],
        "item_code": raw.get("ItemCode"),
        "item_description": raw.get("ItemDescription"),
        "quantity": raw.get("Quantity"),
        "quantity_delivered": raw.get("QuantityDelivered"),
        "unit_price": raw.get("NetPrice"),
        "amount": raw.get("Amount"),
        "delivery_date": parse_odata_date(raw.get("DeliveryDate")),
    }


def sync_all(exact: ExactClient = None, dry_run=False):
    """Haal alle 2026 orders op en sync naar Supabase."""
    if exact is None:
        exact = ExactClient()
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Alle orders van 2026
    log.info("Orders ophalen uit Exact Online (2026)...")
    orders = exact.get("/salesorder/SalesOrders", params={
        "$filter": "OrderDate ge datetime'2026-01-01'",
        "$select": ORDER_FIELDS,
        "$orderby": "OrderDate desc",
    })
    log.info(f"{len(orders)} orders gevonden")

    if dry_run:
        for o in orders[:5]:
            log.info(f"  #{o['OrderNumber']} - {o.get('OrderedByName')} "
                     f"({o.get('CreatorFullName')}) - Status: {o.get('DeliveryStatusDescription')}")
        log.info(f"  ... en {max(0, len(orders)-5)} meer")
        return orders

    # Upsert orders
    for order in orders:
        transformed = transform_order(order)
        result = sb.table("orders").upsert(
            transformed, on_conflict="exact_order_id"
        ).execute()
        db_order = result.data[0]
        order_id = db_order["id"]

        # Orderregels ophalen
        lines = exact.get("/salesorder/SalesOrderLines", params={
            "$filter": f"OrderID eq guid'{order['OrderID']}'",
            "$select": LINE_FIELDS,
        })

        for line in lines:
            line_data = transform_order_line(line, order_id)
            sb.table("order_lines").upsert(
                line_data, on_conflict="exact_line_id"
            ).execute()

        log.info(f"  #{order['OrderNumber']} - {order.get('OrderedByName')} "
                 f"- {len(lines)} regels")

    log.info(f"Sync compleet: {len(orders)} orders")
    return orders


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    dry_run = "--dry-run" in sys.argv
    sync_all(dry_run=dry_run)
```

- [ ] **Step 6: Run tests — verwacht PASS**

Run: `python -m pytest tests/test_sync_orders.py -v`

- [ ] **Step 7: Test dry-run tegen live Exact**

Run: `python sync_orders.py --dry-run`
Expected: Lijst van 2026 orders zonder Supabase writes

- [ ] **Step 8: Run echte sync**

Run: `python sync_orders.py`
Expected: Alle orders + regels in Supabase

- [ ] **Step 9: Verifieer data in Supabase**

Run via MCP: `SELECT source, count(*) FROM orders GROUP BY source`

- [ ] **Step 10: Commit**

```bash
git add exact_client.py sync_orders.py tests/
git commit -m "feat: sync 2026 orders from Exact Online to Supabase"
```

---

## Task 4: Next.js project opzetten

**Files:**
- Create: `dashboard/` (hele Next.js app)

### Doel
Next.js app met Tailwind, Supabase client, basis layout.

- [ ] **Step 1: Maak Next.js project aan**

```bash
cd "C:/Users/migue/Documents/Earth water"
npx create-next-app@latest dashboard --typescript --tailwind --eslint --app --src-dir --no-import-alias
```

- [ ] **Step 2: Installeer Supabase client**

```bash
cd dashboard && npm install @supabase/supabase-js
```

- [ ] **Step 3: Maak .env.local aan**

```bash
# dashboard/.env.local
NEXT_PUBLIC_SUPABASE_URL=https://eqdossfutuairijssdng.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVxZG9zc2Z1dHVhaXJpanNzZG5nIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzU2MzMxODEsImV4cCI6MjA5MTIwOTE4MX0.PZkdUqpnkYMAYItOxRERiNjFj_4YcoJX6iCdHH4u13o
```

- [ ] **Step 4: Maak Supabase client lib**

```typescript
// dashboard/src/lib/supabase.ts
import { createClient } from "@supabase/supabase-js";

export const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
);

export type Order = {
  id: string;
  exact_order_id: string;
  order_number: number;
  order_date: string;
  delivery_status: number;
  delivery_status_description: string;
  invoice_status: number;
  invoice_status_description: string;
  creator: string;
  source: string;
  customer_name: string;
  description: string;
  your_ref: string;
  delivery_date: string;
  amount: number;
  synced_at: string;
};

export type OrderLine = {
  id: string;
  order_id: string;
  exact_line_id: string;
  item_code: string;
  item_description: string;
  quantity: number;
  quantity_delivered: number;
  unit_price: number;
  amount: number;
  delivery_date: string;
};
```

- [ ] **Step 5: Maak layout met basis styling**

```tsx
// dashboard/src/app/layout.tsx
import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Earth Water - Orders",
  description: "Order dashboard voor Earth Water",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="nl">
      <body className="bg-gray-50 min-h-screen">
        <header className="bg-white border-b border-gray-200 px-6 py-4">
          <div className="max-w-7xl mx-auto flex items-center justify-between">
            <h1 className="text-xl font-semibold text-gray-900">
              Earth Water — Orders
            </h1>
            <span className="text-sm text-gray-500">Dashboard</span>
          </div>
        </header>
        <main className="max-w-7xl mx-auto px-6 py-8">
          {children}
        </main>
      </body>
    </html>
  );
}
```

- [ ] **Step 6: Test lokaal**

```bash
cd dashboard && npm run dev
```
Open: http://localhost:3000 — lege pagina met header

- [ ] **Step 7: Commit**

```bash
git add dashboard/
git commit -m "feat: scaffold Next.js dashboard with Supabase client"
```

---

## Task 5: Orders overzichtspagina

**Files:**
- Create: `dashboard/src/components/status-badge.tsx`
- Create: `dashboard/src/components/source-badge.tsx`
- Create: `dashboard/src/components/order-filters.tsx`
- Create: `dashboard/src/components/order-table.tsx`
- Modify: `dashboard/src/app/page.tsx`

### Doel
Tabel met alle orders, filters op bron en status, live data uit Supabase.

- [ ] **Step 1: StatusBadge component**

```tsx
// dashboard/src/components/status-badge.tsx
const STATUS_STYLES: Record<number, { label: string; className: string }> = {
  12: { label: "Open", className: "bg-yellow-100 text-yellow-800" },
  20: { label: "Gedeeltelijk", className: "bg-blue-100 text-blue-800" },
  21: { label: "Volledig", className: "bg-green-100 text-green-800" },
};

export function StatusBadge({ status }: { status: number }) {
  const style = STATUS_STYLES[status] || { label: `Status ${status}`, className: "bg-gray-100 text-gray-800" };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${style.className}`}>
      {style.label}
    </span>
  );
}
```

- [ ] **Step 2: SourceBadge component**

```tsx
// dashboard/src/components/source-badge.tsx
export function SourceBadge({ source }: { source: string }) {
  const isAuto = source === "semso_edi";
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
      isAuto ? "bg-purple-100 text-purple-800" : "bg-orange-100 text-orange-800"
    }`}>
      {isAuto ? "Semso/EDI" : "Handmatig"}
    </span>
  );
}
```

- [ ] **Step 3: OrderFilters component**

```tsx
// dashboard/src/components/order-filters.tsx
"use client";

type FilterProps = {
  source: string;
  status: string;
  onSourceChange: (v: string) => void;
  onStatusChange: (v: string) => void;
};

export function OrderFilters({ source, status, onSourceChange, onStatusChange }: FilterProps) {
  return (
    <div className="flex gap-4 mb-6">
      <select
        value={source}
        onChange={(e) => onSourceChange(e.target.value)}
        className="border border-gray-300 rounded-md px-3 py-2 text-sm bg-white"
      >
        <option value="">Alle bronnen</option>
        <option value="semso_edi">Semso/EDI</option>
        <option value="manual">Handmatig</option>
      </select>
      <select
        value={status}
        onChange={(e) => onStatusChange(e.target.value)}
        className="border border-gray-300 rounded-md px-3 py-2 text-sm bg-white"
      >
        <option value="">Alle statussen</option>
        <option value="12">Open</option>
        <option value="20">Gedeeltelijk</option>
        <option value="21">Volledig</option>
      </select>
    </div>
  );
}
```

- [ ] **Step 4: OrderTable component**

```tsx
// dashboard/src/components/order-table.tsx
import Link from "next/link";
import { Order } from "@/lib/supabase";
import { StatusBadge } from "./status-badge";
import { SourceBadge } from "./source-badge";

export function OrderTable({ orders }: { orders: Order[] }) {
  if (orders.length === 0) {
    return <p className="text-gray-500 text-sm py-8 text-center">Geen orders gevonden.</p>;
  }

  return (
    <div className="overflow-x-auto bg-white rounded-lg shadow">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">#</th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Datum</th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Klant</th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Bron</th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Referentie</th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Bedrag</th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Levering</th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Factuur</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200">
          {orders.map((order) => (
            <tr key={order.id} className="hover:bg-gray-50">
              <td className="px-4 py-3 text-sm">
                <Link href={`/orders/${order.id}`} className="text-blue-600 hover:underline font-medium">
                  {order.order_number}
                </Link>
              </td>
              <td className="px-4 py-3 text-sm text-gray-700">
                {order.order_date ? new Date(order.order_date).toLocaleDateString("nl-NL") : "-"}
              </td>
              <td className="px-4 py-3 text-sm text-gray-900">{order.customer_name || "-"}</td>
              <td className="px-4 py-3"><SourceBadge source={order.source} /></td>
              <td className="px-4 py-3 text-sm text-gray-600">{order.your_ref || "-"}</td>
              <td className="px-4 py-3 text-sm text-gray-700">
                {order.amount != null ? `€ ${order.amount.toFixed(2)}` : "-"}
              </td>
              <td className="px-4 py-3"><StatusBadge status={order.delivery_status} /></td>
              <td className="px-4 py-3 text-sm text-gray-600">
                {order.invoice_status_description || "-"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 5: Hoofdpagina met filters + data**

```tsx
// dashboard/src/app/page.tsx
"use client";

import { useEffect, useState } from "react";
import { supabase, Order } from "@/lib/supabase";
import { OrderTable } from "@/components/order-table";
import { OrderFilters } from "@/components/order-filters";

export default function OrdersPage() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [source, setSource] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    async function fetchOrders() {
      setLoading(true);
      let query = supabase
        .from("orders")
        .select("*")
        .order("order_date", { ascending: false });

      if (source) query = query.eq("source", source);
      if (status) query = query.eq("delivery_status", parseInt(status));

      const { data, error } = await query;
      if (error) console.error("Fout bij ophalen orders:", error);
      setOrders(data || []);
      setLoading(false);
    }
    fetchOrders();
  }, [source, status]);

  const totalAmount = orders.reduce((sum, o) => sum + (o.amount || 0), 0);

  return (
    <div>
      <div className="mb-6 flex items-end justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Bestellingen 2026</h2>
          <p className="text-sm text-gray-500 mt-1">
            {orders.length} orders — totaal € {totalAmount.toFixed(2)}
          </p>
        </div>
      </div>
      <OrderFilters
        source={source}
        status={status}
        onSourceChange={setSource}
        onStatusChange={setStatus}
      />
      {loading ? (
        <p className="text-gray-500 py-8 text-center">Laden...</p>
      ) : (
        <OrderTable orders={orders} />
      )}
    </div>
  );
}
```

- [ ] **Step 6: Test lokaal met data**

```bash
cd dashboard && npm run dev
```
Open: http://localhost:3000 — orders tabel met filters

- [ ] **Step 7: Commit**

```bash
git add dashboard/src/
git commit -m "feat: orders overview page with filters and table"
```

---

## Task 6: Order detail pagina

**Files:**
- Create: `dashboard/src/app/orders/[id]/page.tsx`

### Doel
Detail pagina met order info + alle orderregels (producten).

- [ ] **Step 1: Maak detail pagina**

```tsx
// dashboard/src/app/orders/[id]/page.tsx
"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { supabase, Order, OrderLine } from "@/lib/supabase";
import { StatusBadge } from "@/components/status-badge";
import { SourceBadge } from "@/components/source-badge";

export default function OrderDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [order, setOrder] = useState<Order | null>(null);
  const [lines, setLines] = useState<OrderLine[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetch() {
      const [orderRes, linesRes] = await Promise.all([
        supabase.from("orders").select("*").eq("id", id).single(),
        supabase.from("order_lines").select("*").eq("order_id", id).order("item_code"),
      ]);
      setOrder(orderRes.data);
      setLines(linesRes.data || []);
      setLoading(false);
    }
    fetch();
  }, [id]);

  if (loading) return <p className="text-gray-500 py-8 text-center">Laden...</p>;
  if (!order) return <p className="text-red-500 py-8 text-center">Order niet gevonden.</p>;

  return (
    <div>
      <Link href="/" className="text-sm text-blue-600 hover:underline mb-4 inline-block">
        &larr; Terug naar overzicht
      </Link>

      <div className="bg-white rounded-lg shadow p-6 mb-6">
        <div className="flex items-start justify-between mb-4">
          <div>
            <h2 className="text-2xl font-bold text-gray-900">Order #{order.order_number}</h2>
            <p className="text-gray-600">{order.customer_name}</p>
          </div>
          <div className="flex gap-2">
            <SourceBadge source={order.source} />
            <StatusBadge status={order.delivery_status} />
          </div>
        </div>

        <dl className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div>
            <dt className="text-gray-500">Orderdatum</dt>
            <dd className="font-medium">{order.order_date ? new Date(order.order_date).toLocaleDateString("nl-NL") : "-"}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Leverdatum</dt>
            <dd className="font-medium">{order.delivery_date ? new Date(order.delivery_date).toLocaleDateString("nl-NL") : "-"}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Referentie (PO)</dt>
            <dd className="font-medium">{order.your_ref || "-"}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Bedrag</dt>
            <dd className="font-medium">{order.amount != null ? `€ ${order.amount.toFixed(2)}` : "-"}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Leverstatus</dt>
            <dd className="font-medium">{order.delivery_status_description || "-"}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Factuurstatus</dt>
            <dd className="font-medium">{order.invoice_status_description || "-"}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Aangemaakt door</dt>
            <dd className="font-medium">{order.creator || "-"}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Omschrijving</dt>
            <dd className="font-medium">{order.description || "-"}</dd>
          </div>
        </dl>
      </div>

      <div className="bg-white rounded-lg shadow">
        <div className="px-6 py-4 border-b border-gray-200">
          <h3 className="text-lg font-semibold text-gray-900">
            Orderregels ({lines.length})
          </h3>
        </div>
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Code</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Product</th>
              <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Aantal</th>
              <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Geleverd</th>
              <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Prijs</th>
              <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Bedrag</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {lines.map((line) => (
              <tr key={line.id}>
                <td className="px-4 py-3 text-sm font-mono text-gray-700">{line.item_code}</td>
                <td className="px-4 py-3 text-sm text-gray-900">{line.item_description}</td>
                <td className="px-4 py-3 text-sm text-right">{line.quantity}</td>
                <td className="px-4 py-3 text-sm text-right">{line.quantity_delivered}</td>
                <td className="px-4 py-3 text-sm text-right">
                  {line.unit_price != null ? `€ ${line.unit_price.toFixed(2)}` : "-"}
                </td>
                <td className="px-4 py-3 text-sm text-right font-medium">
                  {line.amount != null ? `€ ${line.amount.toFixed(2)}` : "-"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Test lokaal**

```bash
cd dashboard && npm run dev
```
Klik op een ordernummer → detail pagina met regels

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/app/orders/
git commit -m "feat: order detail page with lines"
```

---

## Task 7: Deploy naar Vercel

- [ ] **Step 1: Push naar GitHub**

```bash
cd "C:/Users/migue/Documents/Earth water"
git remote add origin <github-repo-url>
git push -u origin main
```

- [ ] **Step 2: Deploy via Vercel**

```bash
cd dashboard
npx vercel --prod
```

Of: verbind de GitHub repo in het Vercel dashboard.

Set environment variables in Vercel:
- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`

- [ ] **Step 3: Verifieer live dashboard**

Open de Vercel URL — orders moeten zichtbaar zijn met werkende filters.

- [ ] **Step 4: Commit deploy config**

```bash
git add vercel.json 2>/dev/null; git commit -m "chore: deploy dashboard to Vercel" --allow-empty
```

---

## Openstaande punten

1. **Supabase service_role key** — nodig voor sync script. Ophalen uit Supabase Dashboard → Settings → API.
2. **Gmail credentials** — nog niet ingevuld in `.env`. Nodig voor fase 2b (mail intake).
3. **requirements.txt** — aanmaken met: `requests`, `python-dotenv`, `supabase`
4. **Automatische sync** — nu handmatig via `python sync_orders.py`. Later via n8n of Supabase Edge Function op schedule.
5. **Wat exact_auth.py** — blijft bestaan voor initiële OAuth setup (browser flow). `exact_client.py` is voor alle API-calls daarna.
