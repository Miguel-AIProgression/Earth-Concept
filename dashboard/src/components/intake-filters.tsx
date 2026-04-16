"use client";

import { ParseStatus } from "@/lib/supabase";

const FILTERS: { value: ParseStatus | "all"; label: string }[] = [
  { value: "all", label: "Alles" },
  { value: "pending", label: "Nog te parsen" },
  { value: "needs_review", label: "Review nodig" },
  { value: "ready_for_approval", label: "Wacht op goedkeuring" },
  { value: "approved", label: "Goedgekeurd" },
  { value: "created", label: "In Exact" },
  { value: "test_context", label: "Testmails" },
  { value: "ignored", label: "Genegeerd" },
  { value: "failed", label: "Mislukt" },
];

export function IntakeFilters({
  active,
  onChange,
  counts,
}: {
  active: ParseStatus | "all";
  onChange: (v: ParseStatus | "all") => void;
  counts: Record<string, number>;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {FILTERS.map((f) => {
        const count = f.value === "all"
          ? Object.values(counts).reduce((a, b) => a + b, 0)
          : counts[f.value] ?? 0;
        const isActive = active === f.value;
        return (
          <button
            key={f.value}
            onClick={() => onChange(f.value)}
            className={`text-sm px-3 py-1.5 rounded-full border transition-colors ${
              isActive
                ? "bg-gray-900 text-white border-gray-900"
                : "bg-white text-gray-700 border-gray-200 hover:border-gray-400"
            }`}
          >
            {f.label}
            <span className={`ml-2 text-xs ${isActive ? "text-gray-300" : "text-gray-400"}`}>
              {count}
            </span>
          </button>
        );
      })}
    </div>
  );
}
