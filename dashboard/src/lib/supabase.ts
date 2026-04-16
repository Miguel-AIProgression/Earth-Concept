import { createClient } from "@supabase/supabase-js";

export const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
);

export type ParseStatus =
  | "pending"
  | "parsed"
  | "needs_review"
  | "ready_for_approval"
  | "approved"
  | "created"
  | "test_context"
  | "ignored"
  | "failed";

export type Attachment = {
  filename: string;
  content_type: string;
  storage_path: string;
  size: number;
};

export type ParsedLine = {
  description: string | null;
  item_code: string | null;
  quantity: number | null;
  unit: string | null;
  unit_price: number | null;
};

export type ParsedData = {
  customer_name?: string | null;
  customer_reference?: string | null;
  delivery_date?: string | null;
  delivery_address?: {
    street?: string | null;
    zip?: string | null;
    city?: string | null;
    country?: string | null;
  } | null;
  lines?: ParsedLine[];
  notes?: string | null;
  confidence?: number | null;
  matched_customer?: { id: string; name: string; confidence: number } | null;
  matched_items?: Array<{
    line: ParsedLine;
    item_id: string | null;
    item_code: string | null;
    confidence: number;
  }>;
  match_confidence?: number;
  match_error?: string;
  salesorder_payload?: Record<string, unknown> | null;
};

export type IncomingOrder = {
  id: string;
  received_at: string | null;
  message_id: string;
  from_address: string | null;
  subject: string | null;
  body_text: string | null;
  body_html: string | null;
  attachments: Attachment[] | null;
  parse_status: ParseStatus;
  parsed_data: ParsedData | null;
  exact_order_id: string | null;
  error: string | null;
  created_at: string;
};

