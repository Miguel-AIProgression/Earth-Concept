import Link from "next/link";
import { Order } from "@/lib/supabase";
import { StatusBadge } from "./status-badge";
import { SourceBadge } from "./source-badge";

export function OrderTable({ orders }: { orders: Order[] }) {
  if (orders.length === 0) {
    return (
      <p className="text-gray-500 text-sm py-8 text-center">
        Geen orders gevonden.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto bg-white rounded-lg shadow">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
              #
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
              Datum
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
              Klant
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
              Bron
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
              Referentie
            </th>
            <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
              Bedrag
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
              Levering
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
              Factuur
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200">
          {orders.map((order) => (
            <tr key={order.id} className="hover:bg-gray-50">
              <td className="px-4 py-3 text-sm">
                <Link
                  href={`/orders/${order.id}`}
                  className="text-blue-600 hover:underline font-medium"
                >
                  {order.order_number}
                </Link>
              </td>
              <td className="px-4 py-3 text-sm text-gray-700">
                {order.order_date
                  ? new Date(order.order_date).toLocaleDateString("nl-NL")
                  : "-"}
              </td>
              <td className="px-4 py-3 text-sm text-gray-900">
                {order.customer_name || "-"}
              </td>
              <td className="px-4 py-3">
                <SourceBadge source={order.source} />
              </td>
              <td className="px-4 py-3 text-sm text-gray-600">
                {order.your_ref || "-"}
              </td>
              <td className="px-4 py-3 text-sm text-gray-700 text-right">
                {order.amount != null
                  ? `\u20AC ${Number(order.amount).toFixed(2)}`
                  : "-"}
              </td>
              <td className="px-4 py-3">
                <StatusBadge status={order.delivery_status} />
              </td>
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
