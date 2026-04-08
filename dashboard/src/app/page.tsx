"use client";

import { useEffect, useState } from "react";
import { supabase, Order } from "@/lib/supabase";
import { useAuth } from "@/lib/auth";
import { LoginForm } from "@/components/login-form";
import { OrderFunnel } from "@/components/order-funnel";
import { OrderTable } from "@/components/order-table";
import { OrderFilters } from "@/components/order-filters";

type View = "funnel" | "list";

export default function OrdersPage() {
  const { user, loading: authLoading } = useAuth();
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<View>("funnel");
  const [source, setSource] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    async function fetchOrders() {
      setLoading(true);
      let query = supabase
        .from("orders")
        .select("*")
        .order("order_date", { ascending: false });

      if (source) query = query.eq("source", source);
      if (status) query = query.eq("delivery_status", parseInt(status));

      const { data, error } = await query;
      if (error) console.error("Fout bij ophalen orders:", error);
      setOrders(data || []);
      setLoading(false);
    }
    fetchOrders();
  }, [source, status]);

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
          <button
            onClick={() => setView("funnel")}
            className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
              view === "funnel"
                ? "bg-white text-gray-900 shadow-sm"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            Funnel
          </button>
          <button
            onClick={() => setView("list")}
            className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
              view === "list"
                ? "bg-white text-gray-900 shadow-sm"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            Lijst
          </button>
        </div>
      </div>

      {view === "list" && (
        <OrderFilters
          source={source}
          status={status}
          onSourceChange={setSource}
          onStatusChange={setStatus}
        />
      )}

      {loading ? (
        <p className="text-gray-500 py-8 text-center">Laden...</p>
      ) : view === "funnel" ? (
        <OrderFunnel orders={orders} />
      ) : (
        <OrderTable orders={orders} />
      )}
    </div>
  );
}
