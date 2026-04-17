"use client";

import { useState } from "react";
import { supabase, IncomingOrder, ParseStatus } from "@/lib/supabase";

type ActionKey = "approve" | "ignore" | "retry";

const ACTIONS: Record<
  ActionKey,
  {
    label: string;
    confirm: string;
    className: string;
    toStatus: ParseStatus;
    availableFor: ParseStatus[];
  }
> = {
  approve: {
    label: "Goedkeuren → Exact",
    confirm: "Weet je zeker dat je deze order naar Exact wilt sturen?",
    className: "bg-green-600 hover:bg-green-700 text-white",
    toStatus: "approved",
    availableFor: ["ready_for_approval"],
  },
  ignore: {
    label: "Negeren",
    confirm: "Deze mail markeren als 'negeren' (geen Exact-order)?",
    className: "bg-gray-200 hover:bg-gray-300 text-gray-800",
    toStatus: "ignored",
    availableFor: ["pending", "parsed", "needs_review", "ready_for_approval", "failed", "test_context"],
  },
  retry: {
    label: "Opnieuw parsen",
    confirm: "Parsing opnieuw starten? Status gaat terug naar 'pending'.",
    className: "bg-blue-600 hover:bg-blue-700 text-white",
    toStatus: "pending",
    availableFor: ["failed", "needs_review", "ignored", "test_context"],
  },
};

export function StatusActions({
  row,
  onUpdated,
}: {
  row: IncomingOrder;
  onUpdated: (updated: Partial<IncomingOrder>) => void;
}) {
  const [loading, setLoading] = useState<ActionKey | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(action: ActionKey) {
    const cfg = ACTIONS[action];
    if (!confirm(cfg.confirm)) return;

    setLoading(action);
    setError(null);

    const patch: Partial<IncomingOrder> = {
      parse_status: cfg.toStatus,
      error: null,
    };
    const { error: updateError } = await supabase
      .from("incoming_orders")
      .update(patch)
      .eq("id", row.id);

    if (updateError) {
      setError(updateError.message);
    } else {
      onUpdated(patch);
    }
    setLoading(null);
  }

  if (row.parse_status === "created") {
    return (
      <div className="text-sm text-green-700">
        Order is in Exact aangemaakt — geen handmatige actie meer nodig.
      </div>
    );
  }

  const hasPayload = Boolean(row.parsed_data?.salesorder_payload);
  const blockedReason =
    row.parse_status === "needs_review" && !hasPayload
      ? "Klant- of artikelmatching ontbreekt — pas de gegevens aan of laat opnieuw parsen voordat je naar Exact stuurt."
      : null;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {(Object.keys(ACTIONS) as ActionKey[]).map((key) => {
          const cfg = ACTIONS[key];
          if (!cfg.availableFor.includes(row.parse_status)) return null;
          if (key === "approve" && !hasPayload) return null;
          return (
            <button
              key={key}
              onClick={() => run(key)}
              disabled={loading !== null}
              className={`text-sm px-4 py-2 rounded-lg font-medium transition-colors disabled:opacity-50 ${cfg.className}`}
            >
              {loading === key ? "Bezig…" : cfg.label}
            </button>
          );
        })}
      </div>
      {blockedReason && (
        <p className="text-xs text-amber-700 bg-amber-50 rounded-lg px-3 py-2">
          {blockedReason}
        </p>
      )}
      {error && (
        <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>
      )}
      <p className="text-xs text-gray-500">
        Na &quot;Goedkeuren&quot; duwt de volgende pipeline-run (binnen 5 min) de order naar Exact.
      </p>
    </div>
  );
}
