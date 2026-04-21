import Link from "next/link";
import { IncomingOrder } from "@/lib/supabase";
import { IntakeStatusBadge } from "./intake-status-badge";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("nl-NL", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function cleanFrom(from: string | null): string {
  if (!from) return "—";
  const match = from.match(/^(.*?)<([^>]+)>/);
  if (match) {
    const name = match[1].trim().replace(/"/g, "");
    return name || match[2];
  }
  return from;
}

/**
 * Groepeert mails per thread_id en kiest één "primary" rij per thread:
 * de rij met de meest-gevorderde status (created > approved > ... >
 * needs_review > failed > pending) wint; bij gelijke status de nieuwste.
 * Zo ziet de gebruiker één rij per bestelling, ook als er 3 Fwd:/Re:-
 * mails in dezelfde thread kwamen.
 */
const STATUS_RANK: Record<string, number> = {
  created: 100,
  approved: 90,
  ready_for_approval: 80,
  test_context: 70,
  needs_review: 60,
  parsed: 50,
  pending: 40,
  failed: 20,
  ignored: 10,
};

function groupByThread(rows: IncomingOrder[]): { primary: IncomingOrder; count: number }[] {
  const buckets = new Map<string, IncomingOrder[]>();
  for (const r of rows) {
    const key = r.thread_id || r.id;
    const list = buckets.get(key) ?? [];
    list.push(r);
    buckets.set(key, list);
  }
  const groups = Array.from(buckets.values()).map((list) => {
    const primary = list.reduce((best, cur) => {
      const rankBest = STATUS_RANK[best.parse_status] ?? 0;
      const rankCur = STATUS_RANK[cur.parse_status] ?? 0;
      if (rankCur !== rankBest) return rankCur > rankBest ? cur : best;
      const tBest = new Date(best.received_at ?? best.created_at).getTime();
      const tCur = new Date(cur.received_at ?? cur.created_at).getTime();
      return tCur > tBest ? cur : best;
    });
    return { primary, count: list.length };
  });
  // Sorteer oudste→nieuwste op basis van primary's received_at, descending.
  return groups.sort((a, b) => {
    const ta = new Date(a.primary.received_at ?? a.primary.created_at).getTime();
    const tb = new Date(b.primary.received_at ?? b.primary.created_at).getTime();
    return tb - ta;
  });
}

export function IntakeTable({ rows }: { rows: IncomingOrder[] }) {
  if (rows.length === 0) {
    return (
      <div className="bg-white border border-gray-200 rounded-xl p-12 text-center text-gray-500">
        Geen mails in deze filter.
      </div>
    );
  }

  const groups = groupByThread(rows);

  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 border-b border-gray-200">
          <tr className="text-left text-xs uppercase tracking-wide text-gray-500">
            <th className="px-4 py-3">Ontvangen</th>
            <th className="px-4 py-3">Afzender</th>
            <th className="px-4 py-3">Onderwerp</th>
            <th className="px-4 py-3">Klant (geparsed)</th>
            <th className="px-4 py-3 text-right">Regels</th>
            <th className="px-4 py-3">Bijlage</th>
            <th className="px-4 py-3">Status</th>
            <th className="px-4 py-3">Exact</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {groups.map(({ primary: r, count }) => {
            const parsed = r.parsed_data;
            const lines = parsed?.lines?.length ?? 0;
            const customer = parsed?.customer_name ?? "—";
            const attachCount = r.attachments?.length ?? 0;
            return (
              <tr key={r.thread_id || r.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                  {formatDate(r.received_at ?? r.created_at)}
                </td>
                <td className="px-4 py-3 text-gray-900">{cleanFrom(r.from_address)}</td>
                <td className="px-4 py-3 text-gray-900 max-w-xs truncate">
                  <Link href={`/mail/${r.id}`} className="hover:underline">
                    {r.subject || "(geen onderwerp)"}
                  </Link>
                  {count > 1 && (
                    <span className="ml-2 text-xs text-gray-500 bg-gray-100 rounded px-1.5 py-0.5">
                      {count} mails
                    </span>
                  )}
                </td>
                <td className="px-4 py-3 text-gray-600">{customer}</td>
                <td className="px-4 py-3 text-right text-gray-600">{lines || "—"}</td>
                <td className="px-4 py-3 text-gray-600">
                  {attachCount > 0 ? `${attachCount} stuks` : "—"}
                </td>
                <td className="px-4 py-3">
                  <IntakeStatusBadge status={r.parse_status} />
                </td>
                <td className="px-4 py-3 text-gray-600 font-mono text-xs">
                  {r.exact_order_id ? r.exact_order_id.slice(0, 8) : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
