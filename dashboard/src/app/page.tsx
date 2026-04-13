"use client";

import { useEffect, useState } from "react";
import { supabase, Order } from "@/lib/supabase";
import { useAuth } from "@/lib/auth";
import { LoginForm } from "@/components/login-form";
import { OrderFunnel } from "@/components/order-funnel";
import { OrderTable } from "@/components/order-table";
import { OrderFilters } from "@/components/order-filters";
import { ShippingQueue } from "@/components/shipping-queue";

type View = "shipping" | "funnel" | "list";

export default function OrdersPage() {
  const { user, session, loading: authLoading } = useAuth();
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<View>("shipping");
  const [status, setStatus] = useState("");

  async function fetchOrders() {
    setLoading(true);
    let query = supabase
      .from("orders")
      .select("*")
      .order("order_date", { ascending: false });

    if (status) query = query.eq("delivery_status", parseInt(status));

    const { data, error } = await query;
    if (error) console.error("Fout bij ophalen orders:", error);
    setOrders(data || []);
    setLoading(false);
  }

  useEffect(() => {
    fetchOrders();
  }, [status]);

  function handleOrderShipped(orderId: string) {
    setOrders((prev) =>
      prev.map((o) =>
        o.id === orderId
          ? { ...o, delivery_status: 21, delivery_status_description: "Volledig geleverd" }
          : o
      )
    );
  }

  const totalAmount = orders.reduce(
    (sum, o) => sum + (Number(o.amount) || 0),
    0
  );

  if (authLoading) {
    return <p className="text-gray-500 py-8 text-center">Laden...</p>;
  }

  if (!user) {
    return <LoginForm />;
  }

  return (
    <div>
      <div className="mb-6 flex items-end justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">
            Bestellingen 2026
          </h2>
          <p className="text-sm text-gray-500 mt-1">
            {orders.length} orders &mdash; totaal &euro;{" "}
            {totalAmount.toLocaleString("nl-NL", { minimumFractionDigits: 2 })}
          </p>
        </div>
        <div className="flex bg-gray-100 rounded-lg p-0.5">
          {(["shipping", "funnel", "list"] as const).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
                view === v
                  ? "bg-white text-gray-900 shadow-sm"
                  : "text-gray-500 hover:text-gray-700"
              }`}
            >
              {v === "shipping" ? "Verzenden" : v === "funnel" ? "Funnel" : "Lijst"}
            </button>
          ))}
        </div>
      </div>

      {view === "list" && (
        <OrderFilters
          status={status}
          onStatusChange={setStatus}
        />
      )}

      {loading ? (
        <p className="text-gray-500 py-8 text-center">Laden...</p>
      ) : view === "shipping" ? (
        <ShippingQueue
          orders={orders}
          accessToken={session?.access_token || ""}
          onOrderShipped={handleOrderShipped}
        />
      ) : view === "funnel" ? (
        <OrderFunnel orders={orders} />
      ) : (
        <OrderTable orders={orders} />
      )}
    </div>
  );
}
