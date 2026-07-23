/**
 * E2.7 · Marketplace monetization API client tests.
 */
import assert from 'node:assert';
import test from 'node:test';

interface FetchCall { url: string; init?: RequestInit; }
const calls: FetchCall[] = [];
let responder: (call: FetchCall) => Response = () =>
  new Response('{}', { status: 200 });

const origFetch = globalThis.fetch;
globalThis.fetch = ((input: any, init?: RequestInit) => {
  const url = typeof input === 'string' ? input : input.url;
  calls.push({ url, init });
  return Promise.resolve(responder({ url, init }));
}) as any;

function jsonResp(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

import {
  bpsToPercent, cancelOrder, centsToYuan, createOrder,
  getRevenue, listOrders, listPrices, payOrder, refundOrder,
  retirePrice, upsertPrice,
} from '../lib/marketplace_monetization';

function reset() {
  calls.length = 0;
  responder = () => new Response('{}', { status: 200 });
}

async function runTests() {

  await test('bpsToPercent / centsToYuan formatters', () => {
    assert.strictEqual(bpsToPercent(1500), '15.00%');
    assert.strictEqual(bpsToPercent(725), '7.25%');
    assert.strictEqual(centsToYuan(9900), '¥99.00');
    assert.strictEqual(centsToYuan(0), '¥0.00');
  });

  await test('listPrices default omits retired', async () => {
    reset();
    responder = () => jsonResp(200, []);
    await listPrices('lid-1');
    assert.ok(calls[0].url.endsWith('/lid-1/prices'));

    reset();
    responder = () => jsonResp(200, []);
    await listPrices('lid-2', true);
    assert.match(calls[0].url, /include_retired=true$/);
  });

  await test('upsertPrice POST payload', async () => {
    reset();
    responder = () => jsonResp(201, { id: 'p1' });
    await upsertPrice('lid', {
      plan_code: 'monthly',
      plan_name: '月度',
      billing_mode: 'subscription',
      unit_price_cny_cents: 9900,
      billing_cycle_days: 30,
    });
    assert.strictEqual(calls[0].init?.method, 'POST');
    const body = JSON.parse((calls[0].init?.body as string) ?? '{}');
    assert.strictEqual(body.plan_code, 'monthly');
    assert.strictEqual(body.billing_cycle_days, 30);
  });

  await test('retirePrice DELETE 204', async () => {
    reset();
    responder = () => new Response(null, { status: 204 });
    await retirePrice('p1');
    assert.strictEqual(calls[0].init?.method, 'DELETE');
    assert.match(calls[0].url, /prices\/p1$/);
  });

  await test('getRevenue returns rollup', async () => {
    reset();
    responder = () => jsonResp(200, {
      listing_id: 'lid', paid_orders: 3,
      gross_cny_cents: 30000, platform_fee_cny_cents: 4500,
      vendor_payout_cny_cents: 25500,
    });
    const r = await getRevenue('lid');
    assert.strictEqual(r.paid_orders, 3);
    assert.strictEqual(r.vendor_payout_cny_cents, 25500);
  });

  await test('listOrders status filter propagates', async () => {
    reset();
    responder = () => jsonResp(200, []);
    await listOrders({ status: 'paid', limit: 50 });
    assert.match(calls[0].url, /status_=paid/);
    assert.match(calls[0].url, /limit=50/);
  });

  await test('createOrder POST payload', async () => {
    reset();
    responder = () => jsonResp(201, { id: 'o1' });
    await createOrder('p1', 3, 'ALIPAY-REF');
    assert.strictEqual(calls[0].init?.method, 'POST');
    const body = JSON.parse((calls[0].init?.body as string) ?? '{}');
    assert.strictEqual(body.price_id, 'p1');
    assert.strictEqual(body.units, 3);
    assert.strictEqual(body.external_ref, 'ALIPAY-REF');
  });

  await test('payOrder passes external_ref', async () => {
    reset();
    responder = () => jsonResp(200, { id: 'o1', status: 'paid' });
    await payOrder('o1', 'ALIPAY-XYZ');
    assert.match(calls[0].url, /orders\/o1\/pay$/);
    const body = JSON.parse((calls[0].init?.body as string) ?? '{}');
    assert.strictEqual(body.external_ref, 'ALIPAY-XYZ');
  });

  await test('cancel/refund POST endpoints', async () => {
    reset();
    responder = () => jsonResp(200, { id: 'o1', status: 'cancelled' });
    await cancelOrder('o1');
    assert.match(calls[0].url, /orders\/o1\/cancel$/);

    reset();
    responder = () => jsonResp(200, { id: 'o2', status: 'refunded' });
    await refundOrder('o2');
    assert.match(calls[0].url, /orders\/o2\/refund$/);
  });

  await test('HTTP error surfaces', async () => {
    reset();
    responder = () => new Response('bad', { status: 400 });
    await assert.rejects(() => payOrder('x'), /HTTP 400/);
  });
}

runTests()
  .then(() => { globalThis.fetch = origFetch; })
  .catch((err) => {
    globalThis.fetch = origFetch;
    console.error(err);
    process.exit(1);
  });
