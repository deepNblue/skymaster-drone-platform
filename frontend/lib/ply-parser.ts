/**
 * Minimal PLY (Polygon File Format) parser — v2.1 T1.4.
 *
 * Purpose: parse Gaussian-Splatting .ply files (and generic photogrammetry
 * point clouds) into a Float32Array of xyz + optional Uint8Array of rgb,
 * suitable for feeding a THREE.BufferGeometry as a point cloud.
 *
 * Design goals
 * ------------
 * 1. **Pure function** — no DOM, no THREE, no fetch. Deterministic. Testable
 *    under vitest/jest with plain ArrayBuffer inputs.
 * 2. **Handles binary_little_endian and ascii formats** — the two common
 *    outputs of COLMAP, nerfstudio splatfacto, and Inria gaussian-splatting.
 * 3. **Robust to unknown properties** — 3DGS PLYs have 50+ per-vertex
 *    properties (f_dc_*, scale_*, rot_*, opacity, …). We only care about
 *    x/y/z/red/green/blue; everything else is skipped by width offset.
 * 4. **Rejects malformed files** cleanly — throws PLYParseError with a
 *    diagnostic message, never returns garbage.
 */

export type PLYFormat = 'ascii' | 'binary_little_endian' | 'binary_big_endian';

export interface PLYProperty {
  name: string;
  type: string;
  isList: boolean;
  countType?: string;
  itemType?: string;
}

export interface PLYElement {
  name: string;
  count: number;
  properties: PLYProperty[];
}

export interface PLYHeader {
  format: PLYFormat;
  version: string;
  elements: PLYElement[];
  headerLength: number;
}

export interface PLYPointCloud {
  vertexCount: number;
  positions: Float32Array;      // xyz interleaved, length = 3 * vertexCount
  colors: Uint8Array | null;    // rgb interleaved when present, length = 3 * vertexCount
  hasColor: boolean;
  format: PLYFormat;
}

export class PLYParseError extends Error {
  constructor(msg: string) {
    super(`[PLYParseError] ${msg}`);
  }
}

// Type widths in bytes for binary PLY.
const TYPE_SIZES: Record<string, number> = {
  char: 1, uchar: 1, int8: 1, uint8: 1,
  short: 2, ushort: 2, int16: 2, uint16: 2,
  int: 4, uint: 4, int32: 4, uint32: 4,
  float: 4, float32: 4,
  double: 8, float64: 8,
};

function propertySize(p: PLYProperty): number {
  if (p.isList) {
    throw new PLYParseError(`list property ${p.name} not supported in vertex element`);
  }
  const s = TYPE_SIZES[p.type];
  if (s === undefined) throw new PLYParseError(`unknown type ${p.type}`);
  return s;
}

/**
 * Parse the ASCII header of a PLY buffer.
 * Returns the parsed structure and the byte offset where binary/ascii data starts.
 */
export function parsePLYHeader(buffer: ArrayBuffer): PLYHeader {
  // Header is guaranteed ASCII; scan for "\nend_header\n"
  const bytes = new Uint8Array(buffer);
  // Find "end_header" line terminator
  const marker = 'end_header';
  const dec = new TextDecoder('ascii');
  const maxHeader = Math.min(bytes.length, 1 << 20); // hard-cap at 1MB header
  const headerText = dec.decode(bytes.subarray(0, maxHeader));

  const endIdx = headerText.indexOf(marker);
  if (endIdx < 0) throw new PLYParseError('missing end_header marker');

  // headerLength = end_header line + trailing newline
  // Find the newline right after end_header
  const nlAfter = headerText.indexOf('\n', endIdx);
  if (nlAfter < 0) throw new PLYParseError('no newline after end_header');
  const headerLength = nlAfter + 1;

  const lines = headerText
    .slice(0, endIdx + marker.length)
    .split(/\r?\n/)
    .map(l => l.trim())
    .filter(Boolean);

  if (lines[0] !== 'ply') {
    throw new PLYParseError('file does not start with "ply" magic');
  }

  let format: PLYFormat | null = null;
  let version = '';
  const elements: PLYElement[] = [];
  let currentEl: PLYElement | null = null;

  for (let i = 1; i < lines.length; i++) {
    const line = lines[i];
    if (line.startsWith('comment') || line.startsWith('obj_info')) continue;
    if (line === 'end_header') break;

    const parts = line.split(/\s+/);
    const kw = parts[0];

    if (kw === 'format') {
      if (parts.length < 3) throw new PLYParseError('bad format line');
      const fmt = parts[1];
      if (fmt !== 'ascii' && fmt !== 'binary_little_endian' && fmt !== 'binary_big_endian') {
        throw new PLYParseError(`unknown format ${fmt}`);
      }
      format = fmt as PLYFormat;
      version = parts[2];
    } else if (kw === 'element') {
      if (parts.length < 3) throw new PLYParseError('bad element line');
      currentEl = { name: parts[1], count: parseInt(parts[2], 10), properties: [] };
      if (!Number.isFinite(currentEl.count) || currentEl.count < 0) {
        throw new PLYParseError(`invalid element count: ${parts[2]}`);
      }
      elements.push(currentEl);
    } else if (kw === 'property') {
      if (!currentEl) throw new PLYParseError('property before element');
      if (parts[1] === 'list') {
        if (parts.length < 5) throw new PLYParseError('bad list property');
        currentEl.properties.push({
          name: parts[4], type: 'list', isList: true,
          countType: parts[2], itemType: parts[3],
        });
      } else {
        if (parts.length < 3) throw new PLYParseError('bad property line');
        currentEl.properties.push({ name: parts[2], type: parts[1], isList: false });
      }
    }
  }

  if (!format) throw new PLYParseError('missing format directive');

  return { format, version, elements, headerLength };
}

/**
 * Read one property value from a DataView at the given offset.
 * Returns [value, bytesConsumed].
 */
function readBinaryValue(
  dv: DataView, offset: number, type: string, littleEndian: boolean,
): number {
  switch (type) {
    case 'char': case 'int8': return dv.getInt8(offset);
    case 'uchar': case 'uint8': return dv.getUint8(offset);
    case 'short': case 'int16': return dv.getInt16(offset, littleEndian);
    case 'ushort': case 'uint16': return dv.getUint16(offset, littleEndian);
    case 'int': case 'int32': return dv.getInt32(offset, littleEndian);
    case 'uint': case 'uint32': return dv.getUint32(offset, littleEndian);
    case 'float': case 'float32': return dv.getFloat32(offset, littleEndian);
    case 'double': case 'float64': return dv.getFloat64(offset, littleEndian);
    default: throw new PLYParseError(`unknown binary type ${type}`);
  }
}

/**
 * Parse a full PLY buffer into a point cloud.
 * Only the "vertex" element is read; other elements are ignored.
 *
 * If `maxPoints > 0`, decimation is applied so at most `maxPoints` vertices
 * are kept (uniform stride sample — good enough for preview).
 */
export function parsePLY(
  buffer: ArrayBuffer,
  options: { maxPoints?: number } = {},
): PLYPointCloud {
  const header = parsePLYHeader(buffer);
  const vertexEl = header.elements.find(e => e.name === 'vertex');
  if (!vertexEl) throw new PLYParseError('no vertex element');
  if (vertexEl.count === 0) {
    return {
      vertexCount: 0, positions: new Float32Array(0),
      colors: null, hasColor: false, format: header.format,
    };
  }

  const props = vertexEl.properties;
  const xIdx = props.findIndex(p => p.name === 'x');
  const yIdx = props.findIndex(p => p.name === 'y');
  const zIdx = props.findIndex(p => p.name === 'z');
  if (xIdx < 0 || yIdx < 0 || zIdx < 0) {
    throw new PLYParseError('vertex element missing x/y/z properties');
  }
  const rIdx = props.findIndex(p => p.name === 'red');
  const gIdx = props.findIndex(p => p.name === 'green');
  const bIdx = props.findIndex(p => p.name === 'blue');
  const hasColor = rIdx >= 0 && gIdx >= 0 && bIdx >= 0;

  const maxPoints = options.maxPoints && options.maxPoints > 0
    ? options.maxPoints : vertexEl.count;
  const stride = vertexEl.count > maxPoints
    ? Math.floor(vertexEl.count / maxPoints) : 1;
  const outCount = Math.floor(vertexEl.count / stride);

  const positions = new Float32Array(outCount * 3);
  const colors = hasColor ? new Uint8Array(outCount * 3) : null;

  if (header.format === 'ascii') {
    const text = new TextDecoder('ascii').decode(new Uint8Array(buffer, header.headerLength));
    // Iterate line by line
    const lines = text.split(/\r?\n/);
    let vi = 0;
    let out = 0;
    for (const line of lines) {
      if (!line.trim()) continue;
      if (vi >= vertexEl.count) break;
      if (vi % stride === 0 && out < outCount) {
        const tokens = line.split(/\s+/);
        positions[out * 3 + 0] = parseFloat(tokens[xIdx]);
        positions[out * 3 + 1] = parseFloat(tokens[yIdx]);
        positions[out * 3 + 2] = parseFloat(tokens[zIdx]);
        if (colors) {
          colors[out * 3 + 0] = parseInt(tokens[rIdx], 10);
          colors[out * 3 + 1] = parseInt(tokens[gIdx], 10);
          colors[out * 3 + 2] = parseInt(tokens[bIdx], 10);
        }
        out++;
      }
      vi++;
    }
    return {
      vertexCount: out, positions: positions.subarray(0, out * 3),
      colors: colors ? colors.subarray(0, out * 3) : null,
      hasColor, format: header.format,
    };
  }

  // Binary path — compute offsets per property
  const propOffsets: number[] = [];
  let recordSize = 0;
  for (const p of props) {
    propOffsets.push(recordSize);
    recordSize += propertySize(p);
  }
  const littleEndian = header.format === 'binary_little_endian';
  const dataStart = header.headerLength;
  const expectedEnd = dataStart + recordSize * vertexEl.count;
  if (expectedEnd > buffer.byteLength) {
    throw new PLYParseError(
      `binary data truncated: expected end=${expectedEnd}, buffer=${buffer.byteLength}`,
    );
  }
  const dv = new DataView(buffer);
  let out = 0;
  for (let vi = 0; vi < vertexEl.count; vi++) {
    if (vi % stride !== 0 || out >= outCount) continue;
    const base = dataStart + vi * recordSize;
    positions[out * 3 + 0] = readBinaryValue(dv, base + propOffsets[xIdx], props[xIdx].type, littleEndian);
    positions[out * 3 + 1] = readBinaryValue(dv, base + propOffsets[yIdx], props[yIdx].type, littleEndian);
    positions[out * 3 + 2] = readBinaryValue(dv, base + propOffsets[zIdx], props[zIdx].type, littleEndian);
    if (colors) {
      colors[out * 3 + 0] = readBinaryValue(dv, base + propOffsets[rIdx], props[rIdx].type, littleEndian);
      colors[out * 3 + 1] = readBinaryValue(dv, base + propOffsets[gIdx], props[gIdx].type, littleEndian);
      colors[out * 3 + 2] = readBinaryValue(dv, base + propOffsets[bIdx], props[bIdx].type, littleEndian);
    }
    out++;
  }

  return {
    vertexCount: out, positions: positions.subarray(0, out * 3),
    colors: colors ? colors.subarray(0, out * 3) : null,
    hasColor, format: header.format,
  };
}
