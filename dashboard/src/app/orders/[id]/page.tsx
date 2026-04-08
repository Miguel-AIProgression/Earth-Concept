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
        supabase
          .from("order_lines")
          .select("*")
          .eq("order_id", id)
          .order("item_code"),
      ]);
      setOrder(orderRes.data);
      setLines(linesRes.data || []);
      setLoading(false);
    }
    fetch();
  }, [id]);

  if (loading)
    return <p className="text-gray-500 py-8 text-center">Laden...</p>;
  if (!order)
    return (
      <p className="text-red-500 py-8 text-center">Order niet gevonden.</p>
    );

  const lineTotal = lines.reduce(
    (sum, l) => sum + (Number(l.amount) || 0),
    0
  );

  return (
    <div>
      <Link
        href="/"
        className="text-sm text-blue-600 hover:underline mb-4 inline-block"
      >
        &larr; Terug naar overzicht
      </Link>

      <div className="bg-white rounded-lg shadow p-6 mb-6">
        <div className="flex items-start justify-between mb-4">
          <div>
            <h2 className="text-2xl font-bold text-gray-900">
              Order #{order.order_number}
            </h2>
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
            <dd className="font-medium">
              {order.order_date
                ? new Date(order.order_date).toLocaleDateString("nl-NL")
                : "-"}
            </dd>
          </div>
          <div>
            <dt className="text-gray-500">Leverdatum</dt>
            <dd className="font-medium">
              {order.delivery_date
                ? new Date(order.delivery_date).toLocaleDateString("nl-NL")
                : "-"}
            </dd>
          </div>
          <div>
            <dt className="text-gray-500">Referentie (PO)</dt>
            <dd className="font-medium">{order.your_ref || "-"}</dd>
          </div>
          <div>
            <dt className="text-gray-500">Bedrag</dt>
            <dd className="font-medium">
              {order.amount != null
                ? `\u20AC ${Number(order.amount).toFixed(2)}`
                : "-"}
            </dd>
          </div>
          <div>
            <dt className="text-gray-500">Leverstatus</dt>
            <dd className="font-medium">
              {order.delivery_status_description || "-"}
            </dd>
          </div>
          <div>
            <dt className="text-gray-500">Factuurstatus</dt>
            <dd className="font-medium">
              {order.invoice_status_description || "-"}
            </dd>
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
        {lines.length === 0 ? (
          <p className="text-gray-500 text-sm py-6 text-center">
            Geen orderregels gevonden.
          </p>
        ) : (
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Code
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Product
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                  Aantal
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                  Geleverd
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                  Prijs
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                  Bedrag
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {lines.map((line) => (
                <tr key={line.id}>
                  <td className="px-4 py-3 text-sm font-mono text-gray-700">
                    {line.item_code}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-900">
                    {line.item_description}
                  </td>
                  <td className="px-4 py-3 text-sm text-right">
                    {line.quantity}
                  </td>
                  <td className="px-4 py-3 text-sm text-right">
                    {line.quantity_delivered}
                  </td>
                  <td className="px-4 py-3 text-sm text-right">
                    {line.unit_price != null
                      ? `\u20AC ${Number(line.unit_price).toFixed(2)}`
                      : "-"}
                  </td>
                  <td className="px-4 py-3 text-sm text-right font-medium">
                    {line.amount != null
                      ? `\u20AC ${Number(line.amount).toFixed(2)}`
                      : "-"}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot className="bg-gray-50">
              <tr>
                <td
                  colSpan={5}
                  className="px-4 py-3 text-sm font-medium text-right text-gray-700"
                >
                  Totaal
                </td>
                <td className="px-4 py-3 text-sm text-right font-bold text-gray-900">
                  &euro; {lineTotal.toFixed(2)}
                </td>
              </tr>
            </tfoot>
          </table>
        )}
      </div>
    </div>
  );
}
