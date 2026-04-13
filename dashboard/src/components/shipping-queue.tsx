"use client";

import { useState } from "react";
import Link from "next/link";
import { Order } from "@/lib/supabase";

function isAfhaalOrder(order: Order): boolean {
  const desc = (order.description || "").toLowerCase();
  const customer = (order.customer_name || "").toLowerCase();
  return desc.includes("afhaal") || customer.includes("afhaal");
}

type UrgencyGroup = {
  key: string;
  title: string;
  description: string;
  color: string;
  bgColor: string;
  borderColor: string;
  iconBgColor: string;
  orders: Order[];
};

function toLocalDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("nl-NL", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

function classifyByUrgency(orders: Order[]): UrgencyGroup[] {
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const tomorrow = new Date(today);
  tomorrow.setDate(tomorrow.getDate() + 1);

  const endOfWeek = new Date(today);
  endOfWeek.setDate(endOfWeek.getDate() + (7 - endOfWeek.getDay()));

  const groups: UrgencyGroup[] = [
    {
      key: "overdue",
      title: "Achterstallig",
      description: "Leverdatum is verstreken",
      color: "text-red-700",
      bgColor: "bg-red-50",
      borderColor: "border-red-200",
      iconBgColor: "bg-red-100",
      orders: [],
    },
    {
      key: "today",
      title: "Vandaag verzenden",
      description: "Levering gepland voor vandaag",
      color: "text-orange-700",
      bgColor: "bg-orange-50",
      borderColor: "border-orange-200",
      iconBgColor: "bg-orange-100",
      orders: [],
    },
    {
      key: "tomorrow",
      title: "Morgen",
      description: "Levering gepland voor morgen",
      color: "text-yellow-700",
      bgColor: "bg-yellow-50",
      borderColor: "border-yellow-200",
      iconBgColor: "bg-yellow-100",
      orders: [],
    },
    {
      key: "this_week",
      title: "Deze week",
      description: "Levering gepland deze week",
      color: "text-blue-700",
      bgColor: "bg-blue-50",
      borderColor: "border-blue-200",
      iconBgColor: "bg-blue-100",
      orders: [],
    },
    {
      key: "later",
      title: "Later",
      description: "Levering volgende week of later",
      color: "text-gray-600",
      bgColor: "bg-gray-50",
      borderColor: "border-gray-200",
      iconBgColor: "bg-gray-100",
      orders: [],
    },
  ];

  // Alleen open orders (delivery_status 12 of 20)
  const openOrders = orders
    .filter((o) => o.delivery_status === 12 || o.delivery_status === 20)
    .sort(
      (a, b) =>
        new Date(a.delivery_date || "9999").getTime() -
        new Date(b.delivery_date || "9999").getTime()
    );

  for (const order of openOrders) {
    if (!order.delivery_date) {
      groups[4].orders.push(order); // geen datum = later
      continue;
    }

    const deliveryDate = new Date(order.delivery_date);
    deliveryDate.setHours(0, 0, 0, 0);

    if (deliveryDate < today) {
      groups[0].orders.push(order); // achterstallig
    } else if (deliveryDate.getTime() === today.getTime()) {
      groups[1].orders.push(order); // vandaag
    } else if (deliveryDate.getTime() === tomorrow.getTime()) {
      groups[2].orders.push(order); // morgen
    } else if (deliveryDate <= endOfWeek) {
      groups[3].orders.push(order); // deze week
    } else {
      groups[4].orders.push(order); // later
    }
  }

  return groups;
}

function ShipButton({
  orderId,
  accessToken,
  onShipped,
}: {
  orderId: string;
  accessToken: string;
  onShipped: () => void;
}) {
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleShip(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    if (!confirm("Weet je zeker dat je deze order wilt verzenden?")) return;
    setSending(true);
    setError(null);
    try {
      const res = await fetch(`/api/orders/${orderId}/deliver`, {
        method: "POST",
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.error);
      } else {
        onShipped();
      }
    } catch {
      setError("Netwerkfout");
    } finally {
      setSending(false);
    }
  }

  if (error) {
    return (
      <span className="text-xs text-red-600 max-w-[120px] truncate" title={error}>
        {error}
      </span>
    );
  }

  return (
    <button
      onClick={handleShip}
      disabled={sending}
      className="px-3 py-1 bg-green-600 text-white text-xs font-medium rounded-md hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors whitespace-nowrap"
    >
      {sending ? "Bezig..." : "Verzenden"}
    </button>
  );
}

function GroupCard({
  group,
  defaultOpen,
  accessToken,
  onOrderShipped,
}: {
  group: UrgencyGroup;
  defaultOpen: boolean;
  accessToken: string;
  onOrderShipped: (orderId: string) => void;
}) {
  const [expanded, setExpanded] = useState(defaultOpen);
  const totalAmount = group.orders.reduce(
    (sum, o) => sum + (Number(o.amount) || 0),
    0
  );

  if (group.orders.length === 0) return null;

  return (
    <div
      className={`rounded-xl border ${group.borderColor} ${group.bgColor} overflow-hidden`}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-5 py-4 flex items-center justify-between text-left hover:opacity-80 transition-opacity"
      >
        <div className="flex items-center gap-4">
          <div
            className={`w-10 h-10 rounded-lg ${group.iconBgColor} flex items-center justify-center`}
          >
            <span className={`text-lg font-bold ${group.color}`}>
              {group.orders.length}
            </span>
          </div>
          <div>
            <h3 className={`font-semibold ${group.color}`}>{group.title}</h3>
            <p className="text-xs text-gray-500">{group.description}</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <span className={`text-sm font-medium ${group.color}`}>
            &euro;{" "}
            {totalAmount.toLocaleString("nl-NL", {
              minimumFractionDigits: 2,
            })}
          </span>
          <svg
            className={`w-5 h-5 text-gray-400 transition-transform ${expanded ? "rotate-180" : ""}`}
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={2}
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M19 9l-7 7-7-7"
            />
          </svg>
        </div>
      </button>

      {expanded && (
        <div className="px-5 pb-4">
          <div className="bg-white rounded-lg shadow-sm divide-y divide-gray-100">
            {group.orders.map((order) => (
              <div
                key={order.id}
                className="flex items-center justify-between px-4 py-3 hover:bg-gray-50 transition-colors first:rounded-t-lg last:rounded-b-lg"
              >
                <Link
                  href={`/orders/${order.id}`}
                  className="flex items-center gap-4 min-w-0 flex-1"
                >
                  <span className="text-sm font-medium text-blue-600 shrink-0">
                    #{order.order_number}
                  </span>
                  <span className="text-sm text-gray-900 truncate">
                    {order.customer_name || "-"}
                  </span>
                  {isAfhaalOrder(order) && (
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-800">
                      Afhaal
                    </span>
                  )}
                </Link>
                <div className="flex items-center gap-4 shrink-0">
                  <span className="text-xs text-gray-500">
                    {order.delivery_date
                      ? toLocalDate(order.delivery_date)
                      : "geen datum"}
                  </span>
                  <span className="text-sm font-medium text-gray-700 w-24 text-right">
                    &euro;{" "}
                    {Number(order.amount || 0).toLocaleString("nl-NL", {
                      minimumFractionDigits: 2,
                    })}
                  </span>
                  {isAfhaalOrder(order) ? (
                    <span className="px-3 py-1 text-xs font-medium text-purple-700 whitespace-nowrap">
                      Wordt opgehaald
                    </span>
                  ) : (
                    <ShipButton
                      orderId={order.id}
                      accessToken={accessToken}
                      onShipped={() => onOrderShipped(order.id)}
                    />
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function ShippingQueue({
  orders,
  accessToken,
  onOrderShipped,
}: {
  orders: Order[];
  accessToken: string;
  onOrderShipped: (orderId: string) => void;
}) {
  const groups = classifyByUrgency(orders);
  const totalOpen = groups.reduce((sum, g) => sum + g.orders.length, 0);

  if (totalOpen === 0) {
    return (
      <div className="bg-green-50 border border-green-200 rounded-xl px-6 py-8 text-center">
        <p className="text-green-700 font-medium">
          Alle orders zijn verzonden!
        </p>
      </div>
    );
  }

  const overdueCount = groups[0].orders.length;
  const todayCount = groups[1].orders.length;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-6 mb-4">
        {overdueCount > 0 && (
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-red-400" />
            <span className="text-sm text-gray-600">
              <strong>{overdueCount}</strong> achterstallig
            </span>
          </div>
        )}
        {todayCount > 0 && (
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-orange-400" />
            <span className="text-sm text-gray-600">
              <strong>{todayCount}</strong> vandaag verzenden
            </span>
          </div>
        )}
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-600">
            <strong>{totalOpen}</strong> orders open
          </span>
        </div>
      </div>

      {groups.map((group) => (
        <GroupCard
          key={group.key}
          group={group}
          defaultOpen={group.key !== "later"}
          accessToken={accessToken}
          onOrderShipped={onOrderShipped}
        />
      ))}
    </div>
  );
}
