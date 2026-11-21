// WebSocket helper with auto-reconnect and exponential backoff.

export interface TelemetryPayload {
  drone_id?: string;
  lat?: number;
  lng?: number;
  alt?: number;
  speed?: number;
  battery?: number;
  mode?: string;
  timestamp?: string | number;
  [k: string]: unknown;
}

export type TelemetryCallback = (data: TelemetryPayload) => void;

export interface WsSubscription {
  close: () => void;
  /** Get current connection state — 'connecting' | 'open' | 'reconnecting' | 'closed' */
  getState: () => WsState;
  /** Subscribe to state changes (returns unsubscribe fn) */
  onState: (cb: (s: WsState) => void) => () => void;
}

export type WsState = 'connecting' | 'open' | 'reconnecting' | 'closed';

// Client → Server heartbeat interval. Backend has HEARTBEAT_INTERVAL_S=30
// but ends the socket if no client ping received in 45s → 15s = 3 pings
// of safety margin.
const HEARTBEAT_MS = 15_000;
// If we don't see any server pong/frame within this window, force reconnect.
const STALL_MS = 45_000;

function resolveWsBase(): string {
  const envBase = (process.env.NEXT_PUBLIC_WS_BASE_URL as string | undefined) || '';
  if (envBase) return envBase.replace(/\/$/, '');

  if (typeof window !== 'undefined') {
    const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL as string | undefined) || '';
    if (apiBase) {
      try {
        const u = new URL(apiBase);
        u.protocol = u.protocol === 'https:' ? 'wss:' : 'ws:';
        return u.toString().replace(/\/$/, '');
      } catch {
        /* fall through */
      }
    }
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    // Backend mounts the WS route under /api/v1, so proxy the same prefix
    // when the frontend is served from a different origin.
    return `${proto}//${window.location.hostname}:8000/api/v1`;
  }
  return 'ws://localhost:8000/api/v1';
}

/**
 * Normalize whatever payload shape the backend sends into a flat
 * `TelemetryPayload`. The dev stack emits:
 *   { type: "telemetry", ts, data: { lat, lng, alt, ... } }
 * where all inner values are strings. We coerce to numbers so the map
 * layer can consume them directly.
 */
function normalizeTelemetry(raw: any): TelemetryPayload {
  if (raw == null || typeof raw !== 'object') return {} as TelemetryPayload;
  const inner = (raw.data ?? raw) as Record<string, unknown>;
  const numOrUndef = (v: unknown): number | undefined => {
    if (v == null || v === '') return undefined;
    const n = typeof v === 'number' ? v : Number(v);
    return Number.isFinite(n) ? n : undefined;
  };
  const out: TelemetryPayload = { ...inner };
  const lat = numOrUndef(inner.lat ?? (inner as any).latitude);
  const lng = numOrUndef(inner.lng ?? (inner as any).longitude);
  const alt = numOrUndef(inner.alt ?? (inner as any).altitude);
  const speed = numOrUndef((inner as any).speed ?? (inner as any).groundspeed);
  const heading = numOrUndef((inner as any).heading);
  if (lat !== undefined) out.lat = lat;
  if (lng !== undefined) out.lng = lng;
  if (alt !== undefined) out.alt = alt;
  if (speed !== undefined) (out as any).speed = speed;
  if (heading !== undefined) (out as any).heading = heading;
  if (raw.ts != null) out.timestamp = raw.ts;
  return out;
}

export function subscribeTelemetry(
  droneId: string,
  onMessage: TelemetryCallback
): WsSubscription {
  let ws: WebSocket | null = null;
  let closed = false;
  let attempt = 0;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  let stallTimer: ReturnType<typeof setTimeout> | null = null;
  let lastActivity = Date.now();
  let state: WsState = 'connecting';
  const listeners = new Set<(s: WsState) => void>();

  const setState = (s: WsState) => {
    state = s;
    listeners.forEach((cb) => {
      try {
        cb(s);
      } catch {
        // never let a bad listener break the socket
      }
    });
  };

  const url = `${resolveWsBase()}/ws/telemetry/${encodeURIComponent(droneId)}`;

  const clearTimers = () => {
    if (heartbeatTimer) clearInterval(heartbeatTimer);
    heartbeatTimer = null;
    if (stallTimer) clearTimeout(stallTimer);
    stallTimer = null;
  };

  const armStallTimer = () => {
    if (stallTimer) clearTimeout(stallTimer);
    stallTimer = setTimeout(() => {
      // No activity for STALL_MS → force reconnect. Better UX than
      // silent zombie sockets that keep the app "connected" indefinitely.
      if (!closed && ws) {
        try {
          ws.close(4000, 'client-stall-timeout');
        } catch {
          /* noop */
        }
      }
    }, STALL_MS);
  };

  const connect = () => {
    if (closed) return;
    setState(attempt === 0 ? 'connecting' : 'reconnecting');
    try {
      ws = new WebSocket(url);
    } catch (err) {
      scheduleReconnect();
      return;
    }

    ws.onopen = () => {
      attempt = 0;
      lastActivity = Date.now();
      setState('open');
      // Send periodic client-side heartbeat. Backend `websocket.py`
      // treats any frame as keepalive; we send a small JSON `{type:"ping"}`
      // so the server can also stat client liveness.
      clearTimers();
      heartbeatTimer = setInterval(() => {
        if (ws && ws.readyState === WebSocket.OPEN) {
          try {
            ws.send(JSON.stringify({ type: 'ping', ts: Date.now() }));
          } catch {
            /* noop */
          }
        }
      }, HEARTBEAT_MS);
      armStallTimer();
    };

    ws.onmessage = (evt) => {
      lastActivity = Date.now();
      armStallTimer();
      try {
        const raw =
          typeof evt.data === 'string' ? JSON.parse(evt.data) : evt.data;
        // Skip server-side ping/pong frames (both directions).
        if (raw && (raw.type === 'ping' || raw.type === 'pong')) return;
        onMessage(normalizeTelemetry(raw));
      } catch {
        // ignore malformed frames
      }
    };

    ws.onerror = () => {
      // let onclose handle reconnection
    };

    ws.onclose = () => {
      clearTimers();
      if (!closed) scheduleReconnect();
    };
  };

  const scheduleReconnect = () => {
    if (closed) return;
    setState('reconnecting');
    attempt = Math.min(attempt + 1, 8);
    const delay = Math.min(30_000, 500 * 2 ** (attempt - 1));
    reconnectTimer = setTimeout(connect, delay);
  };

  connect();

  return {
    close() {
      closed = true;
      setState('closed');
      clearTimers();
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (ws && ws.readyState <= 1) {
        try {
          ws.close();
        } catch {
          /* noop */
        }
      }
      ws = null;
    },
    getState() {
      return state;
    },
    onState(cb) {
      listeners.add(cb);
      // Immediately push current state so listener syncs.
      try {
        cb(state);
      } catch {
        /* noop */
      }
      return () => {
        listeners.delete(cb);
      };
    },
  };
}
