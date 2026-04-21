"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { supabase, IncomingOrder, SentEmail } from "@/lib/supabase";
import { useAuth } from "@/lib/auth";
import { LoginForm } from "@/components/login-form";
import { IntakeStatusBadge } from "@/components/intake-status-badge";
import { StatusActions } from "@/components/status-actions";
import { MatchEditor } from "@/components/match-editor";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("nl-NL");
}

export default function MailDetailPage() {
  const { user, session, loading: authLoading } = useAuth();
  const { id } = useParams<{ id: string }>();
  const [row, setRow] = useState<IncomingOrder | null>(null);
  const [sentEmails, setSentEmails] = useState<SentEmail[]>([]);
  const [loading, setLoading] = useState(true);
  const [attachmentUrls, setAttachmentUrls] = useState<Record<string, string>>({});
  const [showHtml, setShowHtml] = useState(false);

  const fetchRow = useCallback(async () => {
    if (!id) return;
    const { data, error } = await supabase
      .from("incoming_orders")
      .select("*")
      .eq("id", id)
      .single();

    if (error) {
      console.error(error);
      setRow(null);
    } else {
      setRow(data as IncomingOrder);
    }
    setLoading(false);
  }, [id]);

  useEffect(() => {
    if (!session) return;
    fetchRow();
  }, [session, fetchRow]);

  useEffect(() => {
    if (!session || !id) return;
    (async () => {
      const { data } = await supabase
        .from("sent_emails")
        .select("*")
        .eq("incoming_order_id", id)
        .order("sent_at", { ascending: false });
      setSentEmails((data as SentEmail[]) || []);
    })();
  }, [session, id, row?.auto_reply_sent_at, row?.confirmation_sent_at]);

  useEffect(() => {
    if (!row?.attachments?.length) return;
    (async () => {
      const urls: Record<string, string> = {};
      for (const a of row.attachments ?? []) {
        const { data } = await supabase.storage
          .from("order-attachments")
          .createSignedUrl(a.storage_path, 300);
        if (data?.signedUrl) urls[a.storage_path] = data.signedUrl;
      }
      setAttachmentUrls(urls);
    })();
  }, [row]);

  if (authLoading) return <div className="text-center text-gray-500 py-12">Laden…</div>;
  if (!user || !session) return <LoginForm />;
  if (loading) return <div className="text-center text-gray-500 py-12">Mail laden…</div>;
  if (!row) return <div className="text-center text-red-600 py-12">Mail niet gevonden.</div>;

  const parsed = row.parsed_data;
  // Alleen regels met daadwerkelijke bestelhoeveelheid tonen.
  // Template-PDF's hebben vaak alle producten als regel met quantity 0.
  const lines = (parsed?.lines ?? []).filter((l) => {
    const q = l.quantity;
    return typeof q === "number" && q > 0;
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <Link href="/" className="text-sm text-gray-500 hover:text-gray-700">
          ← Terug naar overzicht
        </Link>
        <IntakeStatusBadge status={row.parse_status} />
      </div>

      <div className="bg-white border border-gray-200 rounded-xl p-6 space-y-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">{row.subject || "(geen onderwerp)"}</h1>
          <p className="text-sm text-gray-500 mt-1">
            Van <span className="font-medium text-gray-700">{row.from_address || "—"}</span>
            {" · "}
            {formatDate(row.received_at)}
          </p>
        </div>

        {row.error && (
          <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3">
            <p className="text-sm font-medium text-red-800">Foutmelding</p>
            <pre className="text-xs text-red-700 mt-1 whitespace-pre-wrap break-words">
              {row.error}
            </pre>
          </div>
        )}

        {row.exact_order_id && (
          <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-3">
            <p className="text-sm font-medium text-green-800">
              Aangemaakt in Exact als order {row.exact_order_id}
            </p>
          </div>
        )}

        <div className="pt-2 border-t border-gray-100">
          <p className="text-xs uppercase text-gray-500 mb-3">Actie</p>
          <StatusActions
            row={row}
            onUpdated={(patch) => setRow((r) => (r ? { ...r, ...patch } : r))}
          />
        </div>
      </div>

      {(row.attachments?.length ?? 0) > 0 && (
        <div className="bg-white border border-gray-200 rounded-xl p-6">
          <h2 className="text-sm font-semibold text-gray-900 uppercase tracking-wide mb-3">
            Bijlagen
          </h2>
          <ul className="space-y-2">
            {row.attachments?.map((a) => (
              <li key={a.storage_path} className="flex items-center justify-between text-sm">
                <div>
                  <span className="text-gray-900">{a.filename}</span>
                  <span className="text-gray-400 ml-2 text-xs">
                    {a.content_type} · {Math.round(a.size / 1024)} KB
                  </span>
                </div>
                {attachmentUrls[a.storage_path] ? (
                  <a
                    href={attachmentUrls[a.storage_path]}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-600 hover:underline"
                  >
                    Downloaden
                  </a>
                ) : (
                  <span className="text-gray-400 text-xs">Link aan het ophalen…</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {sentEmails.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-xl p-6">
          <h2 className="text-sm font-semibold text-gray-900 uppercase tracking-wide mb-3">
            Verzonden mails
          </h2>
          <ul className="space-y-4">
            {sentEmails.map((e) => (
              <li key={e.id} className="border border-gray-100 rounded-lg p-4">
                <div className="flex items-center justify-between mb-2">
                  <span
                    className={
                      e.type === "confirmation"
                        ? "text-xs font-medium px-2 py-0.5 rounded bg-green-50 text-green-700"
                        : "text-xs font-medium px-2 py-0.5 rounded bg-blue-50 text-blue-700"
                    }
                  >
                    {e.type === "confirmation" ? "Bevestiging" : "Autoreply"}
                  </span>
                  <span className="text-xs text-gray-500">{formatDate(e.sent_at)}</span>
                </div>
                <p className="text-sm text-gray-500">
                  Aan <span className="text-gray-800">{e.to_address}</span>
                </p>
                <p className="text-sm font-medium text-gray-900 mt-1">{e.subject}</p>
                <pre className="text-xs text-gray-700 mt-3 whitespace-pre-wrap break-words bg-gray-50 p-3 rounded border border-gray-100">
                  {e.body}
                </pre>
              </li>
            ))}
          </ul>
        </div>
      )}

      {parsed && row.parse_status !== "created" && (
        <MatchEditor
          row={row}
          onUpdated={(patch) => setRow((r) => (r ? { ...r, ...patch } : r))}
        />
      )}

      {parsed && (
        <div className="bg-white border border-gray-200 rounded-xl p-6 space-y-4">
          <h2 className="text-sm font-semibold text-gray-900 uppercase tracking-wide">
            Geparsed door AI
          </h2>

          <div className="grid grid-cols-2 gap-4 text-sm">
            <Field label="Klant" value={parsed.customer_name} />
            <Field label="Referentie" value={parsed.customer_reference} />
            <Field label="Leverdatum" value={parsed.delivery_date} />
            <Field
              label="Confidence"
              value={
                parsed.confidence != null
                  ? `${Math.round(parsed.confidence * 100)}%`
                  : null
              }
            />
          </div>

          {parsed.delivery_address && (
            <Field
              label="Afleveradres"
              value={[
                parsed.delivery_address.street,
                parsed.delivery_address.zip,
                parsed.delivery_address.city,
                parsed.delivery_address.country,
              ]
                .filter(Boolean)
                .join(", ")}
            />
          )}

          {lines.length > 0 && (
            <div>
              <p className="text-xs uppercase text-gray-500 mb-2">Regels</p>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase text-gray-500 border-b border-gray-200">
                    <th className="py-2">Omschrijving</th>
                    <th className="py-2">Code</th>
                    <th className="py-2 text-right">Aantal</th>
                    <th className="py-2">Unit</th>
                    <th className="py-2 text-right">Prijs</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {lines.map((l, i) => (
                    <tr key={i}>
                      <td className="py-2">{l.description || "—"}</td>
                      <td className="py-2 font-mono text-xs">{l.item_code || "—"}</td>
                      <td className="py-2 text-right">{l.quantity ?? "—"}</td>
                      <td className="py-2 text-gray-500">{l.unit || "—"}</td>
                      <td className="py-2 text-right">
                        {l.unit_price != null ? `€ ${l.unit_price.toFixed(2)}` : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {parsed.matched_customer && (
            <div className="text-xs text-gray-500">
              Gekoppeld aan Exact-klant{" "}
              <span className="font-medium text-gray-700">{parsed.matched_customer.name}</span>{" "}
              ({Math.round((parsed.matched_customer.confidence ?? 0) * 100)}% zeker).
            </div>
          )}
        </div>
      )}

      <div className="bg-white border border-gray-200 rounded-xl p-6">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-gray-900 uppercase tracking-wide">
            Mailtekst
          </h2>
          {row.body_html && (
            <button
              onClick={() => setShowHtml((v) => !v)}
              className="text-xs text-blue-600 hover:underline"
            >
              {showHtml ? "Plain text tonen" : "HTML tonen"}
            </button>
          )}
        </div>
        {showHtml && row.body_html ? (
          <div
            className="prose prose-sm max-w-none"
            dangerouslySetInnerHTML={{ __html: row.body_html }}
          />
        ) : (
          <pre className="text-sm text-gray-700 whitespace-pre-wrap break-words font-sans">
            {row.body_text || "(geen tekst)"}
          </pre>
        )}
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <p className="text-xs uppercase text-gray-500">{label}</p>
      <p className="text-gray-900">{value || "—"}</p>
    </div>
  );
}
