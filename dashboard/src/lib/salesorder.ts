import { ParsedData, MatchedCustomer, MatchedItem } from "./supabase";

/** YYYY-MM-DD -> ISO 8601 datetime zoals Exact in POST-payload accepteert. */
export function dateToODataMs(dateStr: string): string {
  return `${dateStr}T00:00:00`;
}

export function formatDeliveryAddress(
  addr: ParsedData["delivery_address"] | null | undefined
): string | null {
  if (!addr) return null;
  const parts = [addr.street, [addr.zip, addr.city].filter(Boolean).join(" "), addr.country]
    .filter(Boolean)
    .map((v) => (v ?? "").trim())
    .filter(Boolean);
  if (parts.length === 0) return null;
  return parts.join("\n");
}

/**
 * Bouwt een SalesOrder-payload voor Exact Online op basis van de huidige
 * matching. Deze is functioneel equivalent aan build_salesorder_payload
 * in src/order_creator.py.
 *
 * - Items moeten allemaal een item_id hebben, anders null (dan is de rij
 *   nog niet compleet gekoppeld).
 * - Als delivery_address is ingevuld wordt het in Remarks meegenomen
 *   zodat de logistieke partner het ziet; Exact SalesOrders vereist een
 *   Address-GUID voor DeliveryAddress en die kunnen we hier niet op
 *   eigen houtje aanmaken.
 */
export function buildSalesOrderPayload(
  parsed: ParsedData,
  customer: MatchedCustomer,
  items: MatchedItem[],
  opts: { useParsedDeliveryAddress: boolean }
): Record<string, unknown> | null {
  if (!items.length) return null;
  if (items.some((m) => !m.item_id)) return null;

  const lines = items.map((m) => ({
    Item: m.item_id,
    Quantity: m.line.quantity ?? 0,
    UnitPrice: m.line.unit_price ?? 0,
    Description: m.line.description ?? "",
  }));

  const remarks: string[] = [];
  if (parsed.notes) remarks.push(parsed.notes);
  if (opts.useParsedDeliveryAddress) {
    const addr = formatDeliveryAddress(parsed.delivery_address);
    if (addr) remarks.push(`Afleveradres (afwijkend):\n${addr}`);
  }

  const payload: Record<string, unknown> = {
    OrderedBy: customer.id,
    YourRef: parsed.customer_reference ?? "",
    Description: parsed.notes ?? "",
    SalesOrderLines: lines,
  };

  if (parsed.delivery_date) {
    payload.DeliveryDate = dateToODataMs(parsed.delivery_date);
  }

  if (remarks.length > 0) {
    payload.Remarks = remarks.join("\n\n");
  }

  return payload;
}
