/**
 * Standalone parser tests — no vitest/jest infra needed.
 * Run: node --loader ts-node/esm tests/ply-parser.test.mjs
 *
 * We use assert to keep this dependency-free. If the parser regresses,
 * this file will throw with a diagnostic — good enough for a v2.1 milestone.
 */
import assert from 'node:assert';
import { parsePLY, parsePLYHeader, PLYParseError } from '../lib/ply-parser';

/** Encode a UTF-8 string into an ArrayBuffer. */
function enc(s: string): ArrayBuffer {
  const b = new TextEncoder().encode(s);
  return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);
}

/** Concatenate an ASCII header string with a binary payload. */
function concat(header: string, payload: Uint8Array): ArrayBuffer {
  const h = new TextEncoder().encode(header);
  const out = new Uint8Array(h.length + payload.length);
  out.set(h, 0);
  out.set(payload, h.length);
  return out.buffer.slice(0, out.length);
}

let ran = 0;
let failed = 0;
function test(name: string, fn: () => void) {
  ran++;
  try {
    fn();
    console.log(`  ok  · ${name}`);
  } catch (e: any) {
    failed++;
    console.error(`  FAIL · ${name}\n         ${e?.message ?? e}`);
  }
}

console.log('--- parsePLYHeader ---');

test('rejects buffer missing "ply" magic', () => {
  const buf = enc('not_ply\nsomething\nend_header\n');
  assert.throws(() => parsePLYHeader(buf), PLYParseError);
});

test('rejects missing end_header', () => {
  const buf = enc('ply\nformat ascii 1.0\n');
  assert.throws(() => parsePLYHeader(buf), PLYParseError);
});

test('rejects unknown format', () => {
  const buf = enc('ply\nformat weird 1.0\nend_header\n');
  assert.throws(() => parsePLYHeader(buf), PLYParseError);
});

test('parses ascii header with vertex element', () => {
  const buf = enc(
    'ply\n' +
    'format ascii 1.0\n' +
    'comment created by test\n' +
    'element vertex 3\n' +
    'property float x\n' +
    'property float y\n' +
    'property float z\n' +
    'end_header\n',
  );
  const h = parsePLYHeader(buf);
  assert.equal(h.format, 'ascii');
  assert.equal(h.elements.length, 1);
  assert.equal(h.elements[0].name, 'vertex');
  assert.equal(h.elements[0].count, 3);
  assert.equal(h.elements[0].properties.length, 3);
});

test('parses binary_little_endian header with mixed properties', () => {
  const buf = enc(
    'ply\n' +
    'format binary_little_endian 1.0\n' +
    'element vertex 2\n' +
    'property float x\n' +
    'property float y\n' +
    'property float z\n' +
    'property uchar red\n' +
    'property uchar green\n' +
    'property uchar blue\n' +
    'end_header\n',
  );
  const h = parsePLYHeader(buf);
  assert.equal(h.format, 'binary_little_endian');
  assert.equal(h.elements[0].properties.length, 6);
});

console.log('--- parsePLY · ascii ---');

test('parses simple ascii xyz cloud', () => {
  const buf = enc(
    'ply\n' +
    'format ascii 1.0\n' +
    'element vertex 3\n' +
    'property float x\n' +
    'property float y\n' +
    'property float z\n' +
    'end_header\n' +
    '0 0 0\n' +
    '1 2 3\n' +
    '-1 -2 -3\n',
  );
  const cloud = parsePLY(buf);
  assert.equal(cloud.vertexCount, 3);
  assert.equal(cloud.hasColor, false);
  assert.deepStrictEqual(Array.from(cloud.positions), [0, 0, 0, 1, 2, 3, -1, -2, -3]);
});

test('parses ascii cloud with rgb', () => {
  const buf = enc(
    'ply\n' +
    'format ascii 1.0\n' +
    'element vertex 2\n' +
    'property float x\n' +
    'property float y\n' +
    'property float z\n' +
    'property uchar red\n' +
    'property uchar green\n' +
    'property uchar blue\n' +
    'end_header\n' +
    '0 0 0 255 128 0\n' +
    '1 1 1 10 20 30\n',
  );
  const cloud = parsePLY(buf);
  assert.equal(cloud.vertexCount, 2);
  assert.equal(cloud.hasColor, true);
  assert.deepStrictEqual(Array.from(cloud.colors!), [255, 128, 0, 10, 20, 30]);
});

test('rejects missing x/y/z', () => {
  const buf = enc(
    'ply\nformat ascii 1.0\nelement vertex 1\nproperty float w\nend_header\n0\n',
  );
  assert.throws(() => parsePLY(buf), PLYParseError);
});

test('handles vertex count 0', () => {
  const buf = enc(
    'ply\nformat ascii 1.0\n' +
    'element vertex 0\n' +
    'property float x\nproperty float y\nproperty float z\n' +
    'end_header\n',
  );
  const cloud = parsePLY(buf);
  assert.equal(cloud.vertexCount, 0);
  assert.equal(cloud.positions.length, 0);
});

console.log('--- parsePLY · binary ---');

test('parses binary_little_endian xyz cloud', () => {
  const header =
    'ply\n' +
    'format binary_little_endian 1.0\n' +
    'element vertex 2\n' +
    'property float x\nproperty float y\nproperty float z\n' +
    'end_header\n';
  const payload = new Uint8Array(24);
  const dv = new DataView(payload.buffer);
  dv.setFloat32(0, 1.5, true);
  dv.setFloat32(4, 2.5, true);
  dv.setFloat32(8, 3.5, true);
  dv.setFloat32(12, -1, true);
  dv.setFloat32(16, -2, true);
  dv.setFloat32(20, -3, true);
  const cloud = parsePLY(concat(header, payload));
  assert.equal(cloud.vertexCount, 2);
  assert.equal(Math.abs(cloud.positions[0] - 1.5) < 1e-6, true);
  assert.equal(Math.abs(cloud.positions[3] - -1) < 1e-6, true);
});

test('parses binary cloud with rgb', () => {
  const header =
    'ply\n' +
    'format binary_little_endian 1.0\n' +
    'element vertex 1\n' +
    'property float x\nproperty float y\nproperty float z\n' +
    'property uchar red\nproperty uchar green\nproperty uchar blue\n' +
    'end_header\n';
  // 3 floats (12B) + 3 uchars (3B) = 15B
  const payload = new Uint8Array(15);
  const dv = new DataView(payload.buffer);
  dv.setFloat32(0, 0, true);
  dv.setFloat32(4, 0, true);
  dv.setFloat32(8, 0, true);
  payload[12] = 200;
  payload[13] = 100;
  payload[14] = 50;
  const cloud = parsePLY(concat(header, payload));
  assert.equal(cloud.hasColor, true);
  assert.deepStrictEqual(Array.from(cloud.colors!), [200, 100, 50]);
});

test('detects truncated binary payload', () => {
  const header =
    'ply\n' +
    'format binary_little_endian 1.0\n' +
    'element vertex 10\n' +
    'property float x\nproperty float y\nproperty float z\n' +
    'end_header\n';
  const payload = new Uint8Array(24); // Only room for 2 vertices, header claims 10.
  assert.throws(() => parsePLY(concat(header, payload)), PLYParseError);
});

test('decimation via maxPoints reduces vertex count', () => {
  const header =
    'ply\nformat ascii 1.0\n' +
    'element vertex 100\n' +
    'property float x\nproperty float y\nproperty float z\n' +
    'end_header\n';
  const lines = [];
  for (let i = 0; i < 100; i++) lines.push(`${i} ${i} ${i}`);
  const buf = enc(header + lines.join('\n') + '\n');
  const cloud = parsePLY(buf, { maxPoints: 10 });
  // Stride = floor(100/10) = 10 → outCount = floor(100/10) = 10
  assert.equal(cloud.vertexCount, 10);
  assert.equal(cloud.positions[0], 0);
  assert.equal(cloud.positions[3], 10);
  assert.equal(cloud.positions[6], 20);
});

test('skips extraneous 3DGS properties (opacity, scale, rot) without breaking xyz', () => {
  // 3DGS PLYs have 50+ properties. We only care about x/y/z (and rgb if present).
  const header =
    'ply\nformat binary_little_endian 1.0\n' +
    'element vertex 1\n' +
    'property float x\nproperty float y\nproperty float z\n' +
    'property float nx\nproperty float ny\nproperty float nz\n' +
    'property float f_dc_0\nproperty float f_dc_1\nproperty float f_dc_2\n' +
    'property float opacity\n' +
    'property float scale_0\nproperty float scale_1\nproperty float scale_2\n' +
    'property float rot_0\nproperty float rot_1\nproperty float rot_2\nproperty float rot_3\n' +
    'end_header\n';
  // 17 floats × 4B = 68B per vertex
  const payload = new Uint8Array(68);
  const dv = new DataView(payload.buffer);
  dv.setFloat32(0, 7.7, true);
  dv.setFloat32(4, 8.8, true);
  dv.setFloat32(8, 9.9, true);
  // The rest can be zeroed
  const cloud = parsePLY(concat(header, payload));
  assert.equal(cloud.vertexCount, 1);
  assert.equal(cloud.hasColor, false);
  assert.equal(Math.abs(cloud.positions[0] - 7.7) < 1e-4, true);
  assert.equal(Math.abs(cloud.positions[1] - 8.8) < 1e-4, true);
  assert.equal(Math.abs(cloud.positions[2] - 9.9) < 1e-4, true);
});

console.log(`\n${ran - failed}/${ran} tests passed`);
if (failed) {
  process.exit(1);
}
