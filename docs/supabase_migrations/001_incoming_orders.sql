-- Handmatig uitvoeren: storage bucket `order-attachments` aanmaken (private)

create table if not exists incoming_orders (
  id uuid primary key default gen_random_uuid(),
  received_at timestamptz not null,
  message_id text unique not null,
  from_address text,
  subject text,
  body_text text,
  body_html text,
  attachments jsonb default '[]'::jsonb,
  parse_status text not null default 'pending',
  parsed_data jsonb,
  exact_order_id text,
  error text,
  created_at timestamptz default now()
);
create index if not exists incoming_orders_parse_status_idx on incoming_orders(parse_status);
create index if not exists incoming_orders_received_at_idx on incoming_orders(received_at desc);
