'use client';

/**
 * Vision WebSocket hook — subscribes to /ws/vision or /ws/vision/{droneId}.
 *
 * - Auto-reconnects with capped exponential backoff (up to 30 s).
 * - Ships a `bearer` param for JWT auth (matches telemetry/events pattern).
 * - Returns the most recent N frames as a ring buffer plus a live `latest`
 *   reference for the overlay canvas.
 */
import { useEffect, useRef, useState } from 'react';

export interface VisionDetection {
  label: string;
  confidence: number;
  bbox: [number, number, number, number];
  track_id?: number | null;
  attrs?: Record<string, any>;
}

export interface VisionFrameEvent {
  type: 'vision.frame';
  runtime: string;
  model_tag: string;
  latency_ms: number;
  frame_idx: number | null;
  drone_id: string | null;
  mission_id: string | null;
  stream_key: string | null;
  lat: number | null;
  lng: number | null;
  alt_m: number | null;
  detections: VisionDetection[];
  persisted_ids: string[];
  count: number;
  received_at?: number;
}

const MAX_BUFFER = 30;

function apiBase(): string {
  // NEXT_PUBLIC_API_URL is used by lib/api.ts; fall back to same origin.
  if (typeof window === 'undefined') return '';
  const raw = (process.env.NEXT_PUBLIC_API_URL as string) || '';
  if (!raw) return window.location.origin;
  return raw;
}

function wsUrl(path: string, token: string | null): string {
  const base = apiBase().replace(/^http/, 'ws');
  const u = new URL(path, base);
  if (token) u.searchParams.set('token', token);
  return u.toString();
}

export function useVisionStream(droneId?: string) {
  const [connected, setConnected] = useState(false);
  const [latest, setLatest] = useState<VisionFrameEvent | null>(null);
  const [frames, setFrames] = useState<VisionFrameEvent[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const attemptRef = useRef(0);
  const stopRef = useRef(false);

  useEffect(() => {
    stopRef.current = false;
    const token =
      typeof window !== 'undefined'
        ? window.localStorage.getItem('token')
        : null;

    const path = droneId
      ? `/api/v1/ws/vision/${encodeURIComponent(droneId)}`
      : '/api/v1/ws/vision';

    const connect = () => {
      if (stopRef.current) return;
      try {
        const ws = new WebSocket(wsUrl(path, token));
        wsRef.current = ws;
        ws.onopen = () => {
          attemptRef.current = 0;
          setConnected(true);
        };
        ws.onclose = () => {
          setConnected(false);
          if (stopRef.current) return;
          attemptRef.current += 1;
          const delay = Math.min(30000, 500 * 2 ** attemptRef.current);
          setTimeout(connect, delay);
        };
        ws.onerror = () => {
          // let onclose handle reconnect
          try { ws.close(); } catch { /* noop */ }
        };
        ws.onmessage = (ev) => {
          try {
            const payload = JSON.parse(ev.data) as VisionFrameEvent;
            if (payload.type !== 'vision.frame') return;
            payload.received_at = Date.now();
            setLatest(payload);
            setFrames((prev) => {
              const next = [...prev, payload];
              return next.length > MAX_BUFFER
                ? next.slice(next.length - MAX_BUFFER)
                : next;
            });
          } catch {
            /* ignore malformed frames */
          }
        };
      } catch {
        // connect failed sync — retry
        attemptRef.current += 1;
        const delay = Math.min(30000, 500 * 2 ** attemptRef.current);
        setTimeout(connect, delay);
      }
    };

    connect();
    return () => {
      stopRef.current = true;
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) ws.close();
      wsRef.current = null;
    };
  }, [droneId]);

  return { connected, latest, frames };
}
