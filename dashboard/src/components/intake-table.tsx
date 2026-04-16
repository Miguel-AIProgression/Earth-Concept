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

export function IntakeTable({ rows }: { rows: IncomingOrder[] }) {
  if (rows.length === 0) {
    return (
      <div className="bg-white border border-gray-200 rounded-xl p-12 text-center text-gray-500">
        Geen mails in deze filter.
      </div>
    );
  }

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
          {rows.map((r) => {
            const parsed = r.parsed_data;
            const lines = parsed?.lines?.length ?? 0;
            const customer = parsed?.customer_name ?? "—";
            const attachCount = r.attachments?.length ?? 0;
            return (
              <tr key={r.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                  {formatDate(r.received_at ?? r.created_at)}
                </td>
                <td className="px-4 py-3 text-gray-900">{cleanFrom(r.from_address)}</td>
                <td className="px-4 py-3 text-gray-900 max-w-xs truncate">
                  <Link href={`/mail/${r.id}`} className="hover:underline">
                    {r.subject || "(geen onderwerp)"}
                  </Link>
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
