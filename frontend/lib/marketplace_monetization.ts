/**
 * E2.7 · Marketplace monetization API client.
 */
const baseURL =
  process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8080';

function authHeaders(): HeadersInit {
  if (typeof window === 'undefined') return {};
  const t = window.localStorage.getItem('access_token');
  return t ? { Authorization: `Bearer ${t}` } : {};
}

export type BillingMode =
  | 'one_off' | 'subscription' | 'metered' | 'free_trial';

export type OrderStatus =
  | 'pending' | 'paid' | 'cancelled' | 'refunded';

export interface ListingPrice {
  id: string;
  listing_id: string;
  plan_code: string;
  plan_name: string;
  billing_mode: BillingMode;
  unit_price_cny_cents: number;
  included_quota: number;
  billing_cycle_days: number | null;
  platform_fee_bps: number;
  currency: string;
  retired: boolean;
  note: string | null;
  created_at: string;
}

export interface UpsertPricePayload {
  plan_code: string;
  plan_name: string;
  billing_mode: BillingMode;
  unit_price_cny_cents: number;
  included_quota?: number;
  billing_cycle_days?: number | null;
  platform_fee_bps?: number;
  note?: string | null;
}

export interface PurchaseOrder {
  id: string;
  org_id: string;
  user_id: string;
  listing_id: string;
  price_id: string;
  plan_code: string;
  billing_mode: BillingMode;
  units: number;
  total_cny_cents: number;
  platform_fee_cny_cents: number;
  vendor_payout_cny_cents: number;
  status: OrderStatus;
  external_ref: string | null;
  activated_at: string | null;
  expires_at: string | null;
  created_at: string;
}

export interface RevenueRollup {
  listing_id: string;
  paid_orders: number;
  gross_cny_cents: number;
  platform_fee_cny_cents: number;
  vendor_payout_cny_cents: number;
}

async function _do<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${baseURL}/api/v1${path}`, {
    ...init,
    headers: {
      ...authHeaders(),
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!resp.ok && resp.status !== 204) {
    throw new Error(`HTTP ${resp.status} — ${await resp.text()}`);
  }
  if (resp.status === 204) return undefined as unknown as T;
  return resp.json();
}

/** BPS (basis points) → percentage string. 1500 → "15.00%" */
export function bpsToPercent(bps: number): string {
  return `${(bps / 100).toFixed(2)}%`;
}

/** Cents (integer) → yuan display, e.g. 9900 → "¥99.00". */
export function centsToYuan(cents: number): string {
  return `¥${(cents / 100).toFixed(2)}`;
}

// ---- Pricing ----------------------------------------------------------

export function listPrices(
  listingId: string, includeRetired = false,
): Promise<ListingPrice[]> {
  const q = includeRetired ? '?include_retired=true' : '';
  return _do(
    `/marketplace/listings/${encodeURIComponent(listingId)}/prices${q}`,
  );
}

export function upsertPrice(
  listingId: string, payload: UpsertPricePayload,
): Promise<ListingPrice> {
  return _do(
    `/marketplace/listings/${encodeURIComponent(listingId)}/prices`,
    { method: 'POST', body: JSON.stringify(payload) },
  );
}

export function retirePrice(priceId: string): Promise<void> {
  return _do(
    `/marketplace/prices/${encodeURIComponent(priceId)}`,
    { method: 'DELETE' },
  );
}

export function getRevenue(listingId: string): Promise<RevenueRollup> {
  return _do(
    `/marketplace/listings/${encodeURIComponent(listingId)}/revenue`,
  );
}

// ---- Orders -----------------------------------------------------------

export function listOrders(
  opts: { status?: OrderStatus; limit?: number } = {},
): Promise<PurchaseOrder[]> {
  const p = new URLSearchParams();
  if (opts.status) p.set('status_', opts.status);
  if (opts.limit != null) p.set('limit', String(opts.limit));
  const qs = p.toString();
  return _do(`/marketplace/orders${qs ? '?' + qs : ''}`);
}

export function createOrder(
  priceId: string, units = 1, externalRef?: string | null,
): Promise<PurchaseOrder> {
  return _do('/marketplace/orders', {
    method: 'POST',
    body: JSON.stringify({
      price_id: priceId,
      units,
      external_ref: externalRef ?? null,
    }),
  });
}

export function payOrder(
  orderId: string, externalRef?: string | null,
): Promise<PurchaseOrder> {
  return _do(
    `/marketplace/orders/${encodeURIComponent(orderId)}/pay`,
    {
      method: 'POST',
      body: JSON.stringify({ external_ref: externalRef ?? null }),
    },
  );
}

export function cancelOrder(orderId: string): Promise<PurchaseOrder> {
  return _do(
    `/marketplace/orders/${encodeURIComponent(orderId)}/cancel`,
    { method: 'POST' },
  );
}

export function refundOrder(orderId: string): Promise<PurchaseOrder> {
  return _do(
    `/marketplace/orders/${encodeURIComponent(orderId)}/refund`,
    { method: 'POST' },
  );
}
