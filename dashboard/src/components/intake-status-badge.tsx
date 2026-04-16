import { ParseStatus } from "@/lib/supabase";

const STATUS_STYLES: Record<ParseStatus, { label: string; className: string }> = {
  pending: { label: "Nog te parsen", className: "bg-gray-100 text-gray-700" },
  parsed: { label: "Geparsed", className: "bg-blue-100 text-blue-800" },
  needs_review: { label: "Review nodig", className: "bg-amber-100 text-amber-800" },
  ready_for_approval: { label: "Wacht op goedkeuring", className: "bg-indigo-100 text-indigo-800" },
  approved: { label: "Goedgekeurd (wacht op POST)", className: "bg-purple-100 text-purple-800" },
  created: { label: "In Exact aangemaakt", className: "bg-green-100 text-green-800" },
  test_context: { label: "Testmail (niet naar Exact)", className: "bg-slate-100 text-slate-700" },
  ignored: { label: "Genegeerd", className: "bg-slate-100 text-slate-500" },
  failed: { label: "Mislukt", className: "bg-red-100 text-red-800" },
};

export function IntakeStatusBadge({ status }: { status: ParseStatus }) {
  const style = STATUS_STYLES[status] ?? {
    label: status,
    className: "bg-gray-100 text-gray-800",
  };
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${style.className}`}
    >
      {style.label}
    </span>
  );
}
