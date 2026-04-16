"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { supabase, IncomingOrder, ParseStatus } from "@/lib/supabase";
import { useAuth } from "@/lib/auth";
import { LoginForm } from "@/components/login-form";
import { IntakeFilters } from "@/components/intake-filters";
import { IntakeTable } from "@/components/intake-table";

export default function IntakePage() {
  const { user, session, loading: authLoading } = useAuth();
  const [rows, setRows] = useState<IncomingOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<ParseStatus | "all">("all");

  const fetchRows = useCallback(async () => {
    setLoading(true);
    const { data, error } = await supabase
      .from("incoming_orders")
      .select("*")
      .order("received_at", { ascending: false })
      .limit(200);

    if (error) {
      console.error("Fout bij ophalen incoming_orders:", error);
      setRows([]);
    } else {
      setRows((data as IncomingOrder[]) ?? []);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    if (!session) return;
    fetchRows();
    const interval = setInterval(fetchRows, 30_000);
    return () => clearInterval(interval);
  }, [session, fetchRows]);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const r of rows) {
      c[r.parse_status] = (c[r.parse_status] ?? 0) + 1;
    }
    return c;
  }, [rows]);

  const filtered = useMemo(
    () => (filter === "all" ? rows : rows.filter((r) => r.parse_status === filter)),
    [rows, filter]
  );

  if (authLoading) {
    return <div className="text-center text-gray-500 py-12">Laden…</div>;
  }
  if (!user || !session) {
    return <LoginForm />;
  }

  const errorCount = counts.failed ?? 0;
  const totalToday = rows.filter((r) => {
    const d = new Date(r.received_at ?? r.created_at);
    const today = new Date();
    return d.toDateString() === today.toDateString();
  }).length;

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Order-intake</h1>
          <p className="text-sm text-gray-500 mt-1">
            Automatische verwerking van mails naar{" "}
            <span className="font-mono text-xs bg-gray-100 px-1.5 py-0.5 rounded">
              orders@earthwater.nl
            </span>
          </p>
        </div>
        <div className="flex gap-3">
          <StatCard label="Vandaag binnen" value={totalToday} />
          <StatCard label="In Exact gezet" value={counts.created ?? 0} color="green" />
          <StatCard
            label="Review nodig"
            value={(counts.needs_review ?? 0) + (counts.ready_for_approval ?? 0)}
            color="amber"
          />
          <StatCard label="Mislukt" value={errorCount} color="red" />
        </div>
      </div>

      <IntakeFilters active={filter} onChange={setFilter} counts={counts} />

      {loading && rows.length === 0 ? (
        <div className="text-center text-gray-500 py-12">Mails ophalen…</div>
      ) : (
        <IntakeTable rows={filtered} />
      )}

      <div className="text-xs text-gray-400 text-center">
        Auto-refresh elke 30 seconden. Pipeline draait elke 5 minuten via GitHub Actions.
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  color = "gray",
}: {
  label: string;
  value: number;
  color?: "gray" | "green" | "amber" | "red";
}) {
  const colorMap = {
    gray: "text-gray-900",
    green: "text-green-700",
    amber: "text-amber-700",
    red: "text-red-700",
  };
  return (
    <div className="bg-white border border-gray-200 rounded-lg px-4 py-2 min-w-[100px]">
      <div className={`text-2xl font-semibold ${colorMap[color]}`}>{value}</div>
      <div className="text-xs text-gray-500 uppercase tracking-wide">{label}</div>
    </div>
  );
}
