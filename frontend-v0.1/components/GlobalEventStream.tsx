'use client';

import { useEffect } from 'react';
import { message } from 'antd';

/**
 * Subscribes to backend `/api/v1/ws/events` and fires an antd toast when a
 * `mission.completed` event arrives. Zero UI footprint — just a side effect.
 */
export default function GlobalEventStream() {
  useEffect(() => {
    const base =
      (process.env.NEXT_PUBLIC_WS_BASE_URL as string | undefined) ||
      (typeof window !== 'undefined'
        ? `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.hostname}:8000/api/v1`
        : 'ws://localhost:8000/api/v1');

    let ws: WebSocket | null = null;
    let closed = false;
    let backoffMs = 500;
    let reconnectTimer: any = null;

    const connect = () => {
      const url = `${base.replace(/\/$/, '')}/ws/events`;
      ws = new WebSocket(url);
      ws.onopen = () => {
        backoffMs = 500;
      };
      ws.onmessage = (e) => {
        try {
          const m = JSON.parse(e.data);
          if (m?.type === 'mission.completed') {
            const sysid = m?.data?.sysid ?? '?';
            const prog = m?.data?.mission_progress ?? '';
            message.success(`🎯 无人机 ${sysid} 任务完成 · ${prog}`, 4);
          }
        } catch {/* ignore */}
      };
      ws.onclose = () => {
        if (closed) return;
        reconnectTimer = setTimeout(connect, backoffMs);
        backoffMs = Math.min(backoffMs * 2, 8000);
      };
      ws.onerror = () => {/* swallow — onclose will fire */};
    };

    connect();
    return () => {
      closed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, []);

  return null;
}
