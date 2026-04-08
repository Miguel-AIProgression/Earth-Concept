import { createClient } from "@supabase/supabase-js";
import { NextRequest } from "next/server";

const EXACT_TOKEN_URL = "https://start.exactonline.nl/api/oauth2/token";
const CONFIG_KEY = "exact_tokens";
const GUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function supabaseAdmin() {
  return createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_KEY!
  );
}

async function authenticateRequest(request: NextRequest) {
  const authHeader = request.headers.get("authorization");
  if (!authHeader?.startsWith("Bearer ")) return null;
  const sb = supabaseAdmin();
  const { data: { user }, error } = await sb.auth.getUser(authHeader.split(" ")[1]);
  if (error || !user) return null;
  return user;
}

async function loadTokens(sb: ReturnType<typeof supabaseAdmin>) {
  const { data } = await sb
    .from("config")
    .select("value")
    .eq("key", CONFIG_KEY)
    .single();
  if (!data) throw new Error("Exact tokens niet gevonden in database");
  return data.value as { access_token: string; refresh_token: string };
}

async function saveTokens(
  sb: ReturnType<typeof supabaseAdmin>,
  tokens: Record<string, unknown>
) {
  await sb
    .from("config")
    .upsert(
      { key: CONFIG_KEY, value: tokens, updated_at: new Date().toISOString() },
      { onConflict: "key" }
    );
}

async function refreshAccessToken(
  sb: ReturnType<typeof supabaseAdmin>,
  refreshToken: string
) {
  const res = await fetch(EXACT_TOKEN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "refresh_token",
      refresh_token: refreshToken,
      client_id: process.env.EXACT_CLIENT_ID!,
      client_secret: process.env.EXACT_CLIENT_SECRET!,
    }),
  });
  if (!res.ok) throw new Error(`Token refresh mislukt: ${res.status}`);
  const tokens = await res.json();
  await saveTokens(sb, tokens);
  return tokens.access_token as string;
}

async function exactGet(
  accessToken: string,
  endpoint: string,
  params?: Record<string, string>
) {
  const division = process.env.EXACT_DIVISION!;
  let url = `https://start.exactonline.nl/api/v1/${division}${endpoint}`;
  if (params) {
    url += "?" + new URLSearchParams(params).toString();
  }
  const res = await fetch(url, {
    headers: {
      Authorization: `Bearer ${accessToken}`,
      Accept: "application/json",
    },
  });
  if (!res.ok) throw new Error(`Exact API fout: ${res.status}`);
  const json = await res.json();
  return json.d?.results ?? [];
}

async function exactPost(
  accessToken: string,
  endpoint: string,
  payload: unknown
) {
  const division = process.env.EXACT_DIVISION!;
  const url = `https://start.exactonline.nl/api/v1/${division}${endpoint}`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Exact API POST fout: ${res.status} — ${text}`);
  }
  return res.json();
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    // Auth check
    const user = await authenticateRequest(request);
    if (!user) {
      return Response.json({ error: "Niet geautoriseerd" }, { status: 401 });
    }

    const { id } = await params;
    const sb = supabaseAdmin();

    // 1. Haal order op uit Supabase om exact_order_id te krijgen
    const { data: order, error: orderError } = await sb
      .from("orders")
      .select("exact_order_id, order_number, description, delivery_date, delivery_status")
      .eq("id", id)
      .single();

    if (orderError || !order) {
      return Response.json({ error: "Order niet gevonden" }, { status: 404 });
    }

    if (order.delivery_status === 21) {
      return Response.json(
        { error: "Order is al volledig geleverd" },
        { status: 400 }
      );
    }

    // Valideer GUID formaat
    if (!GUID_RE.test(order.exact_order_id)) {
      return Response.json({ error: "Ongeldige order ID" }, { status: 400 });
    }

    // 2. Haal Exact tokens op + refresh als nodig
    let tokens = await loadTokens(sb);
    let accessToken = tokens.access_token;

    // Probeer orderregels op te halen, refresh token bij 401
    let lines: Array<Record<string, number | string>>;
    try {
      lines = await exactGet(accessToken, "/salesorder/SalesOrderLines", {
        $filter: `OrderID eq guid'${order.exact_order_id}'`,
        $select:
          "ID,OrderID,OrderNumber,ItemCode,ItemDescription,Quantity,QuantityDelivered,DeliveryDate",
      });
    } catch (e: unknown) {
      if (e instanceof Error && e.message.includes("401")) {
        accessToken = await refreshAccessToken(sb, tokens.refresh_token);
        lines = await exactGet(accessToken, "/salesorder/SalesOrderLines", {
          $filter: `OrderID eq guid'${order.exact_order_id}'`,
          $select:
            "ID,OrderID,OrderNumber,ItemCode,ItemDescription,Quantity,QuantityDelivered,DeliveryDate",
        });
      } else {
        throw e;
      }
    }

    // 3. Filter op ongeleverde regels
    const undelivered = lines.filter(
      (l) => (l.Quantity as number) > ((l.QuantityDelivered as number) || 0)
    );

    if (undelivered.length === 0) {
      return Response.json(
        { error: "Geen openstaande regels om te leveren" },
        { status: 400 }
      );
    }

    // 4. Maak GoodsDelivery aan
    const deliveryLines = undelivered.map((l) => ({
      SalesOrderLineID: l.ID,
      QuantityDelivered:
        (l.Quantity as number) - ((l.QuantityDelivered as number) || 0),
    }));

    const payload = {
      Description: order.description || "",
      DeliveryDate: order.delivery_date,
      GoodsDeliveryLines: deliveryLines,
    };

    const result = await exactPost(
      accessToken,
      "/salesorder/GoodsDeliveries",
      payload
    );

    const deliveryNumber = result?.d?.DeliveryNumber;

    // Optimistic update: markeer als volledig geleverd in Supabase
    // zodat dubbele verzendingen voorkomen worden (sync corrigeert later als nodig)
    await sb
      .from("orders")
      .update({
        delivery_status: 21,
        delivery_status_description: "Volledig geleverd",
      })
      .eq("id", id);

    return Response.json({
      success: true,
      delivery_number: deliveryNumber,
      lines_count: deliveryLines.length,
    });
  } catch (e: unknown) {
    const message = e instanceof Error ? e.message : "Onbekende fout";
    console.error("GoodsDelivery fout:", message);
    return Response.json({ error: message }, { status: 500 });
  }
}
