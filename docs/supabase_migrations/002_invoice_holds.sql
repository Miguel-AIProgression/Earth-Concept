create table if not exists invoice_holds (
  id uuid primary key default gen_random_uuid(),
  order_number text not null,
  order_id text,
  status text not null default 'review',  -- review|ready_to_invoice|invoiced|cancelled
  match_data jsonb not null,
  discrepancies jsonb default '[]'::jsonb,
  exact_invoice_id text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);
create unique index if not exists invoice_holds_order_number_idx on invoice_holds(order_number);
