"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  supabase,
  IncomingOrder,
  ExactAccount,
  ExactItem,
  MatchedCustomer,
  MatchedItem,
  ParsedLine,
} from "@/lib/supabase";
import { buildSalesOrderPayload, formatDeliveryAddress } from "@/lib/salesorder";

const NORMALIZE_STRIP = /\b(b\.?v\.?|n\.?v\.?|v\.?o\.?f\.?|c\.?v\.?|ltd|limited|gmbh|s\.?a\.?|sas|sarl|inc|llc|co\.?)\b/gi;
const NORMALIZE_NONALNUM = /[^a-z0-9]+/g;

function normalizeName(value: string | null | undefined): string {
  if (!value) return "";
  return value
    .toLowerCase()
    .replace(NORMALIZE_STRIP, " ")
    .replace(NORMALIZE_NONALNUM, " ")
    .trim()
    .replace(/\s+/g, " ");
}

type Props = {
  row: IncomingOrder;
  onUpdated: (updated: Partial<IncomingOrder>) => void;
};

export function MatchEditor({ row, onUpdated }: Props) {
  const parsed = row.parsed_data;
  // Template-bestellijsten (Archeon, Horeca e.d.) hebben tientallen regels
  // met quantity 0 voor niet-bestelde producten; filter die weg.
  const parsedLines: ParsedLine[] = useMemo(
    () =>
      (parsed?.lines ?? []).filter((l) => {
        const q = l.quantity;
        return typeof q === "number" && q > 0;
      }),
    [parsed]
  );

  const [customer, setCustomer] = useState<MatchedCustomer | null>(
    parsed?.matched_customer ?? null
  );
  const [items, setItems] = useState<MatchedItem[]>(() => {
    if (parsed?.matched_items && parsed.matched_items.length === parsedLines.length) {
      return parsed.matched_items as MatchedItem[];
    }
    return parsedLines.map((line) => ({
      line,
      item_id: null,
      item_code: null,
      confidence: 0,
    }));
  });
  const [useDeliveryAddress, setUseDeliveryAddress] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const allItemsMatched = items.length > 0 && items.every((i) => i.item_id);
  const canSave = Boolean(customer && allItemsMatched);

  const updateItem = (index: number, patch: Partial<MatchedItem>) => {
    setItems((prev) => prev.map((it, i) => (i === index ? { ...it, ...patch } : it)));
  };

  const save = useCallback(async () => {
    if (!parsed || !customer) return;
    setSaving(true);
    setError(null);
    setSavedMsg(null);

    try {
      // 1. Sla aliases op zodat het systeem leert voor volgende orders.
      if (parsed.customer_name && customer.id) {
        const alias = parsed.customer_name;
        const aliasNorm = normalizeName(alias);
        if (aliasNorm) {
          await supabase
            .from("customer_aliases")
            .upsert(
              {
                alias,
                alias_normalized: aliasNorm,
                account_id: customer.id,
                source: "manual",
              },
              { onConflict: "alias_normalized" }
            );
        }
      }
      for (const m of items) {
        if (!m.item_id) continue;
        const aliasText = m.line.description;
        if (!aliasText) continue;
        const aliasNorm = normalizeName(aliasText);
        if (!aliasNorm) continue;
        await supabase
          .from("item_aliases")
          .upsert(
            {
              alias: aliasText,
              alias_normalized: aliasNorm,
              item_id: m.item_id,
              source: "manual",
            },
            { onConflict: "alias_normalized" }
          );
      }

      // 2. Bouw payload in dezelfde vorm als de Python-side.
      const payload = buildSalesOrderPayload(parsed, customer, items, {
        useParsedDeliveryAddress: useDeliveryAddress,
      });

      if (!payload) {
        throw new Error("Payload kon niet worden gebouwd");
      }

      // 3. Update de rij: matched data + payload + status.
      const newParsed = {
        ...parsed,
        matched_customer: customer,
        matched_items: items,
        match_confidence: 1.0,
        salesorder_payload: payload,
      };

      const { error: updErr } = await supabase
        .from("incoming_orders")
        .update({
          parsed_data: newParsed,
          parse_status: "ready_for_approval",
          error: null,
        })
        .eq("id", row.id);

      if (updErr) throw updErr;

      onUpdated({
        parsed_data: newParsed,
        parse_status: "ready_for_approval",
        error: null,
      });
      setSavedMsg("Koppeling opgeslagen — klik Goedkeuren om de order naar Exact te sturen.");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }, [parsed, customer, items, useDeliveryAddress, row.id, onUpdated]);

  if (!parsed) return null;
  if (row.parse_status === "created") return null;

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-6 space-y-6">
      <div>
        <h2 className="text-sm font-semibold text-gray-900 uppercase tracking-wide">
          Matching — klant &amp; artikelen
        </h2>
        <p className="text-xs text-gray-500 mt-1">
          Koppel de geparsede gegevens aan Exact-records. De koppeling wordt onthouden
          voor toekomstige orders.
        </p>
      </div>

      <CustomerPicker
        parsedName={parsed.customer_name ?? null}
        current={customer}
        onChange={setCustomer}
      />

      <ItemsPicker
        items={items}
        onChange={updateItem}
      />

      <DeliveryAddressBlock
        parsed={parsed}
        customerId={customer?.id ?? null}
        enabled={useDeliveryAddress}
        onToggle={setUseDeliveryAddress}
      />

      <div className="flex items-center gap-3 pt-2 border-t border-gray-100">
        <button
          onClick={save}
          disabled={!canSave || saving}
          className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium px-4 py-2 rounded-lg"
        >
          {saving ? "Opslaan…" : "Koppeling opslaan"}
        </button>
        {!canSave && (
          <p className="text-xs text-amber-700">
            Kies eerst een klant en koppel elke regel aan een Exact-artikel.
          </p>
        )}
        {savedMsg && <p className="text-xs text-green-700">{savedMsg}</p>}
        {error && <p className="text-xs text-red-700">{error}</p>}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */

function CustomerPicker({
  parsedName,
  current,
  onChange,
}: {
  parsedName: string | null;
  current: MatchedCustomer | null;
  onChange: (m: MatchedCustomer | null) => void;
}) {
  const [query, setQuery] = useState(parsedName ?? "");
  const [results, setResults] = useState<ExactAccount[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!query || query.length < 2) {
      setResults([]);
      return;
    }
    const handle = setTimeout(async () => {
      const norm = normalizeName(query);
      const { data } = await supabase
        .from("exact_accounts")
        .select("id,code,name,name_normalized,email")
        .or(`name.ilike.%${query}%,name_normalized.ilike.%${norm}%`)
        .limit(20);
      setResults((data ?? []) as ExactAccount[]);
    }, 200);
    return () => clearTimeout(handle);
  }, [query]);

  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between">
        <p className="text-xs uppercase text-gray-500">Klant uit mail</p>
        {current && (
          <p className="text-xs text-green-700">
            Gekoppeld: <span className="font-medium">{current.name}</span>
          </p>
        )}
      </div>
      <div className="text-sm text-gray-900">{parsedName || "—"}</div>

      <div className="relative">
        <input
          type="text"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          placeholder="Zoek Exact-klant…"
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        {open && results.length > 0 && (
          <ul className="absolute z-10 mt-1 w-full bg-white border border-gray-200 rounded-lg shadow-md max-h-60 overflow-auto">
            {results.map((acc) => (
              <li
                key={acc.id}
                onClick={() => {
                  onChange({ id: acc.id, name: acc.name, confidence: 1.0, source: "manual" });
                  setQuery(acc.name);
                  setOpen(false);
                }}
                className="px-3 py-2 text-sm cursor-pointer hover:bg-blue-50 flex justify-between"
              >
                <span>{acc.name}</span>
                {acc.code && (
                  <span className="text-xs text-gray-400 font-mono">{acc.code.trim()}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */

function ItemsPicker({
  items,
  onChange,
}: {
  items: MatchedItem[];
  onChange: (index: number, patch: Partial<MatchedItem>) => void;
}) {
  return (
    <div className="space-y-2">
      <p className="text-xs uppercase text-gray-500">Regels</p>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs uppercase text-gray-500 border-b border-gray-200">
            <th className="py-2">Omschrijving uit mail</th>
            <th className="py-2">Klant-code</th>
            <th className="py-2 text-right">Aantal</th>
            <th className="py-2 w-80">Exact-artikel</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {items.map((it, i) => (
            <tr key={i} className="align-top">
              <td className="py-2 pr-2">{it.line.description || "—"}</td>
              <td className="py-2 pr-2 font-mono text-xs text-gray-500">
                {it.line.item_code || "—"}
              </td>
              <td className="py-2 pr-2 text-right">
                {it.line.quantity ?? "—"} {it.line.unit || ""}
              </td>
              <td className="py-2">
                <ItemPicker
                  parsedDescription={it.line.description ?? ""}
                  current={it}
                  onPick={(item) =>
                    onChange(i, {
                      item_id: item.id,
                      item_code: item.code,
                      item_description: item.description,
                      confidence: 1.0,
                      source: "manual",
                    })
                  }
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ItemPicker({
  parsedDescription,
  current,
  onPick,
}: {
  parsedDescription: string;
  current: MatchedItem;
  onPick: (item: ExactItem) => void;
}) {
  const [query, setQuery] = useState(current.item_code ? "" : parsedDescription.slice(0, 30));
  const [results, setResults] = useState<ExactItem[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!query || query.length < 2) {
      setResults([]);
      return;
    }
    const handle = setTimeout(async () => {
      const { data } = await supabase
        .from("exact_items")
        .select("id,code,description,description_normalized")
        .or(`code.ilike.%${query}%,description.ilike.%${query}%`)
        .limit(20);
      setResults((data ?? []) as ExactItem[]);
    }, 200);
    return () => clearTimeout(handle);
  }, [query]);

  return (
    <div className="relative">
      {current.item_id ? (
        <div className="flex items-center justify-between gap-2 bg-green-50 border border-green-200 rounded-lg px-2 py-1.5">
          <div className="min-w-0">
            <p className="text-xs text-gray-900 truncate">{current.item_description ?? "—"}</p>
            <p className="text-xs text-gray-500 font-mono">{current.item_code}</p>
          </div>
          <button
            onClick={() => {
              setQuery(parsedDescription.slice(0, 30));
              setOpen(true);
              onPick({ id: "", code: "", description: "", description_normalized: "" });
            }}
            className="text-xs text-gray-500 hover:text-gray-700"
          >
            wijzigen
          </button>
        </div>
      ) : (
        <input
          type="text"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          placeholder="Zoek EW-code of omschrijving…"
          className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      )}
      {open && results.length > 0 && !current.item_id && (
        <ul className="absolute z-20 mt-1 w-full bg-white border border-gray-200 rounded-lg shadow-md max-h-60 overflow-auto">
          {results.map((it) => (
            <li
              key={it.id}
              onClick={() => {
                onPick(it);
                setOpen(false);
              }}
              className="px-2 py-1.5 text-xs cursor-pointer hover:bg-blue-50"
            >
              <div className="font-mono text-gray-500">{it.code}</div>
              <div className="text-gray-900">{it.description}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */

function DeliveryAddressBlock({
  parsed,
  customerId,
  enabled,
  onToggle,
}: {
  parsed: IncomingOrder["parsed_data"];
  customerId: string | null;
  enabled: boolean;
  onToggle: (v: boolean) => void;
}) {
  const [defaultAddr, setDefaultAddr] = useState<string | null>(null);

  useEffect(() => {
    if (!customerId) {
      setDefaultAddr(null);
      return;
    }
    (async () => {
      const { data } = await supabase
        .from("exact_accounts")
        .select("raw")
        .eq("id", customerId)
        .single();
      const raw = data?.raw as Record<string, unknown> | null;
      if (!raw) return;
      const line1 = (raw.AddressLine1 as string) || "";
      const line2 = (raw.AddressLine2 as string) || "";
      const zip = (raw.Postcode as string) || "";
      const city = (raw.City as string) || "";
      const country = (raw.Country as string) || "";
      const formatted = [line1, line2, [zip, city].filter(Boolean).join(" "), country]
        .map((s) => s.trim())
        .filter(Boolean)
        .join("\n");
      setDefaultAddr(formatted || null);
    })();
  }, [customerId]);

  const parsedAddrStr = formatDeliveryAddress(parsed?.delivery_address);
  if (!parsedAddrStr) return null;

  return (
    <div className="space-y-2">
      <p className="text-xs uppercase text-gray-500">Afleveradres</p>
      <div className="grid md:grid-cols-2 gap-3 text-sm">
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-3">
          <p className="text-xs uppercase text-gray-500 mb-1">Uit mail</p>
          <pre className="whitespace-pre-wrap font-sans text-gray-900">{parsedAddrStr}</pre>
        </div>
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-3">
          <p className="text-xs uppercase text-gray-500 mb-1">Exact-default van klant</p>
          <pre className="whitespace-pre-wrap font-sans text-gray-900">
            {defaultAddr || "—"}
          </pre>
        </div>
      </div>
      <label className="flex items-center gap-2 text-xs text-gray-600">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => onToggle(e.target.checked)}
        />
        Gebruik afleveradres uit de mail (wordt als opmerking in de SalesOrder meegezet).
      </label>
    </div>
  );
}
