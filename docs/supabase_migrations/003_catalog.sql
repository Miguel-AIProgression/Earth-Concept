-- Katalogus van Exact Online in Supabase: lokaal snel doorzoekbaar en
-- resistent tegen Exact API-uitval. Wordt nightly gesynced door
-- src/catalog_sync.py.

create table if not exists exact_accounts (
  id text primary key,             -- Exact Account.ID (GUID)
  code text,
  name text not null,
  name_normalized text not null,
  email text,
  is_active boolean default true,
  raw jsonb,
  synced_at timestamptz default now()
);
create index if not exists exact_accounts_name_norm_idx on exact_accounts(name_normalized);
create index if not exists exact_accounts_code_idx on exact_accounts(code);

create table if not exists exact_items (
  id text primary key,             -- Exact Item.ID
  code text,
  description text not null,
  description_normalized text not null,
  unit text,
  barcode text,
  is_active boolean default true,
  raw jsonb,
  synced_at timestamptz default now()
);
create index if not exists exact_items_code_idx on exact_items(code);
create index if not exists exact_items_desc_norm_idx on exact_items(description_normalized);

-- Self-learning aliases: elke handmatige correctie wordt vastgelegd zodat
-- de matcher bij een volgende keer direct hit.
create table if not exists customer_aliases (
  id uuid primary key default gen_random_uuid(),
  alias text not null,
  alias_normalized text not null,
  account_id text not null references exact_accounts(id) on delete cascade,
  source text not null default 'manual',   -- manual | auto | import
  created_at timestamptz default now(),
  unique (alias_normalized)
);
create index if not exists customer_aliases_norm_idx on customer_aliases(alias_normalized);

create table if not exists item_aliases (
  id uuid primary key default gen_random_uuid(),
  alias text not null,
  alias_normalized text not null,
  item_id text not null references exact_items(id) on delete cascade,
  source text not null default 'manual',
  created_at timestamptz default now(),
  unique (alias_normalized)
);
create index if not exists item_aliases_norm_idx on item_aliases(alias_normalized);
