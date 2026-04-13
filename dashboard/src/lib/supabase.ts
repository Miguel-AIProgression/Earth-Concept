import { createClient } from "@supabase/supabase-js";

export const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
);

export type Order = {
  id: string;
  exact_order_id: string;
  order_number: number;
  order_date: string;
  delivery_status: number;
  delivery_status_description: string;
  invoice_status: number;
  invoice_status_description: string;
  creator: string;
  customer_name: string;
  description: string;
  your_ref: string;
  delivery_date: string;
  amount: number;
  synced_at: string;
};

export type OrderLine = {
  id: string;
  order_id: string;
  exact_line_id: string;
  item_code: string;
  item_description: string;
  quantity: number;
  quantity_delivered: number;
  unit_price: number;
  amount: number;
  delivery_date: string;
};
