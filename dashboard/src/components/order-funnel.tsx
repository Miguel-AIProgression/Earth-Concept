"use client";

import { useState } from "react";
import Link from "next/link";
import { Order } from "@/lib/supabase";
import { SourceBadge } from "./source-badge";

type FunnelStage = {
  key: string;
  title: string;
  description: string;
  color: string;
  bgColor: string;
  borderColor: string;
  iconBgColor: string;
  orders: Order[];
};

function classifyOrders(orders: Order[]): FunnelStage[] {
  const stages: FunnelStage[] = [
    {
      key: "delivery_open",
      title: "Levering openstaand",
      description: "Orders die nog verzonden moeten worden",
      color: "text-red-700",
      bgColor: "bg-red-50",
      borderColor: "border-red-200",
      iconBgColor: "bg-red-100",
      orders: [],
    },
    {
      key: "delivery_partial",
      title: "Gedeeltelijk geleverd",
      description: "Orders die deels verzonden zijn",
      color: "text-amber-700",
      bgColor: "bg-amber-50",
      borderColor: "border-amber-200",
      iconBgColor: "bg-amber-100",
      orders: [],
    },
    {
      key: "to_invoice",
      title: "Te factureren",
      description: "Geleverd, factuur nog open",
      color: "text-blue-700",
      bgColor: "bg-blue-50",
      borderColor: "border-blue-200",
      iconBgColor: "bg-blue-100",
      orders: [],
    },
    {
      key: "done",
      title: "Afgerond",
      description: "Volledig geleverd en gefactureerd",
      color: "text-green-700",
      bgColor: "bg-green-50",
      borderColor: "border-green-200",
      iconBgColor: "bg-green-100",
      orders: [],
    },
  ];

  for (const order of orders) {
    const delivery = order.delivery_status;
    const invoiceDesc = (order.invoice_status_description || "").toLowerCase();

    if (delivery === 12) {
      // Open delivery
      stages[0].orders.push(order);
    } else if (delivery === 20) {
      // Partial delivery
      stages[1].orders.push(order);
    } else if (delivery === 21 && invoiceDesc !== "volledig") {
      // Fully delivered but not yet invoiced
      stages[2].orders.push(order);
    } else {
      // Done
      stages[3].orders.push(order);
    }
  }

  return stages;
}

function StageCard({ stage, defaultOpen }: { stage: FunnelStage; defaultOpen: boolean }) {
  const [expanded, setExpanded] = useState(defaultOpen);
  const totalAmount = stage.orders.reduce((sum, o) => sum + (Number(o.amount) || 0), 0);

  return (
    <div className={`rounded-xl border ${stage.borderColor} ${stage.bgColor} overflow-hidden`}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-5 py-4 flex items-center justify-between text-left hover:opacity-80 transition-opacity"
      >
        <div className="flex items-center gap-4">
          <div className={`w-10 h-10 rounded-lg ${stage.iconBgColor} flex items-center justify-center`}>
            <span className={`text-lg font-bold ${stage.color}`}>{stage.orders.length}</span>
          </div>
          <div>
            <h3 className={`font-semibold ${stage.color}`}>{stage.title}</h3>
            <p className="text-xs text-gray-500">{stage.description}</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <span className={`text-sm font-medium ${stage.color}`}>
            &euro; {totalAmount.toLocaleString("nl-NL", { minimumFractionDigits: 2 })}
          </span>
          <svg
            className={`w-5 h-5 text-gray-400 transition-transform ${expanded ? "rotate-180" : ""}`}
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={2}
            stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </button>

      {expanded && stage.orders.length > 0 && (
        <div className="px-5 pb-4">
          <div className="bg-white rounded-lg shadow-sm divide-y divide-gray-100">
            {stage.orders.map((order) => (
              <Link
                key={order.id}
                href={`/orders/${order.id}`}
                className="flex items-center justify-between px-4 py-3 hover:bg-gray-50 transition-colors first:rounded-t-lg last:rounded-b-lg"
              >
                <div className="flex items-center gap-4 min-w-0">
                  <span className="text-sm font-medium text-blue-600 shrink-0">
                    #{order.order_number}
                  </span>
                  <span className="text-sm text-gray-900 truncate">
                    {order.customer_name || "-"}
                  </span>
                  <SourceBadge source={order.source} />
                </div>
                <div className="flex items-center gap-4 shrink-0">
                  <span className="text-xs text-gray-500">
                    {order.your_ref || ""}
                  </span>
                  <span className="text-sm font-medium text-gray-700 w-24 text-right">
                    &euro; {Number(order.amount || 0).toLocaleString("nl-NL", { minimumFractionDigits: 2 })}
                  </span>
                  <span className="text-xs text-gray-400">
                    {order.order_date
                      ? new Date(order.order_date).toLocaleDateString("nl-NL")
                      : ""}
                  </span>
                </div>
              </Link>
            ))}
          </div>
        </div>
      )}

      {expanded && stage.orders.length === 0 && (
        <div className="px-5 pb-4">
          <p className="text-sm text-gray-400 text-center py-3">Geen orders in deze stap</p>
        </div>
      )}
    </div>
  );
}

export function OrderFunnel({ orders }: { orders: Order[] }) {
  const stages = classifyOrders(orders);
  const actionRequired = stages[0].orders.length + stages[1].orders.length + stages[2].orders.length;

  return (
    <div className="space-y-3">
      {/* Summary bar */}
      <div className="flex items-center gap-6 mb-4">
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-red-400" />
          <span className="text-sm text-gray-600">
            <strong>{actionRequired}</strong> orders vereisen actie
          </span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-green-400" />
          <span className="text-sm text-gray-600">
            <strong>{stages[3].orders.length}</strong> afgerond
          </span>
        </div>
      </div>

      {/* Funnel stages - action stages open by default, done collapsed */}
      {stages.map((stage) => (
        <StageCard
          key={stage.key}
          stage={stage}
          defaultOpen={stage.key !== "done"}
        />
      ))}
    </div>
  );
}
