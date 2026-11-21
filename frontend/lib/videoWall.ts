'use client';

/**
 * Video Wall data layer — combines three backend sources with graceful
 * degradation so the wall keeps working when individual pieces are down
 * (e.g. MediaMTX not running, or the `video_streams` table absent):
 *
 *   1. GET /api/v1/drones/stats     → fleet roster (drone_id / sn / online)
 *   2. GET /api/v1/video-streams    → DB registry (bitrate / res / fps ...)
 *   3. GET /api/v1/streams          → MediaMTX live paths (ready + hls_url)
 *
 * Only #1 is required. #2 and #3 are best-effort: any failure is swallowed
 * and treated as "no data", matching the mock/dev deployment where neither
 * the registry table nor MediaMTX are provisioned.
 *
 * Custom (operator-supplied) HLS URLs are persisted in localStorage so a
 * tile can be pointed at any external feed without a backend write — this
 * is the "假流地址管理" fallback.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from './api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface FleetDrone {
  drone_id: string;
  sn: string;
  online: boolean;
}

export interface VideoStreamRegistry {
  id: string;
  drone_id: string | null;
  name: string;
  protocol: string;
  source_url: string;
  play_url: string | null;
  status: 'idle' | 'active' | 'stopped' | 'error' | string;
  bitrate_kbps: number | null;
  width: number | null;
  height: number | null;
  fps: number | null;
  codec: string | null;
  stale: boolean;
  last_seen_at: string | null;
}

export interface MediaMtxStream {
  name: string;
  drone_id: string | null;
  ready: boolean;
  source: string | null;
  tracks: unknown[];
  hls_url: string | null;
  rtsp_url: string | null;
}

export interface TileSource {
  drone: FleetDrone;
  registry: VideoStreamRegistry | null;
  mediamtx: MediaMtxStream | null;
  /** Resolved playback URL (registry → mediamtx → custom), or null. */
  hlsUrl: string | null;
  /** Where the resolved URL came from, for the UI badge. */
  source: 'registry' | 'mediamtx' | 'custom' | 'none';
  customUrl: string | null;
}

export interface VideoWallData {
  drones: FleetDrone[];
  tiles: TileSource[];
  loading: boolean;
  /** Increments on every successful/manual refresh — used to trigger reconnect. */
  refreshTick: number;
  refresh: () => void;
  setCustomUrl: (droneId: string, url: string | null) => void;
}

// ---------------------------------------------------------------------------
// Custom URL persistence (localStorage)
// ---------------------------------------------------------------------------

const CUSTOM_URL_PREFIX = 'skymaster:videowall:url:';

export function getCustomUrl(droneId: string): string | null {
  if (typeof window === 'undefined') return null;
  const v = window.localStorage.getItem(CUSTOM_URL_PREFIX + droneId);
  return v && v.trim() ? v.trim() : null;
}

function setCustomUrlStored(droneId: string, url: string | null) {
  if (typeof window === 'undefined') return;
  const k = CUSTOM_URL_PREFIX + droneId;
  if (url && url.trim()) window.localStorage.setItem(k, url.trim());
  else window.localStorage.removeItem(k);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function resolveTile(
  drone: FleetDrone,
  registryByDrone: Map<string, VideoStreamRegistry>,
  mediamtxByDrone: Map<string, MediaMtxStream>,
  customUrl: string | null,
): TileSource {
  const reg = registryByDrone.get(drone.drone_id) ?? null;
  const mt = mediamtxByDrone.get(drone.drone_id) ?? null;

  // Preference order: registry play_url (if active) → mediamtx (if ready)
  // → operator custom URL.
  if (reg && reg.status === 'active' && reg.play_url) {
    return { drone, registry: reg, mediamtx: mt, hlsUrl: reg.play_url, source: 'registry', customUrl };
  }
  if (mt && mt.ready && mt.hls_url) {
    return { drone, registry: reg, mediamtx: mt, hlsUrl: mt.hls_url, source: 'mediamtx', customUrl };
  }
  if (customUrl) {
    return { drone, registry: reg, mediamtx: mt, hlsUrl: customUrl, source: 'custom', customUrl };
  }
  // Last resort: a registry entry that exists but isn't active still carries
  // a play_url we can attempt (the player will show its own error state).
  if (reg && reg.play_url) {
    return { drone, registry: reg, mediamtx: mt, hlsUrl: reg.play_url, source: 'registry', customUrl };
  }
  return { drone, registry: reg, mediamtx: mt, hlsUrl: null, source: 'none', customUrl };
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useVideoWallData(pollMs = 10_000): VideoWallData {
  const [drones, setDrones] = useState<FleetDrone[]>([]);
  const [registry, setRegistry] = useState<VideoStreamRegistry[]>([]);
  const [mediamtx, setMediamtx] = useState<MediaMtxStream[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshTick, setRefreshTick] = useState(0);
  const [customUrls, setCustomUrls] = useState<Record<string, string | null>>({});
  const mountedRef = useRef(true);

  // Load custom URLs once on mount (client only).
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const fetchAll = async () => {
    // Fleet roster is authoritative; run all three in parallel.
    const results = await Promise.allSettled([
      api.get<{ per_drone: FleetDrone[] }>('/api/v1/drones/stats'),
      api.get<VideoStreamRegistry[]>('/api/v1/video-streams'),
      api.get<{ items: MediaMtxStream[] }>('/api/v1/streams'),
    ]);

    if (!mountedRef.current) return;

    if (results[0].status === 'fulfilled') {
      const perDrone = results[0].value.data?.per_drone ?? [];
      setDrones(perDrone);
    }
    // Best-effort: registry may 500 when the table is absent (dev).
    if (results[1].status === 'fulfilled') {
      const data = results[1].value.data;
      setRegistry(Array.isArray(data) ? data : []);
    } else {
      setRegistry([]);
    }
    // Best-effort: MediaMTX may be unreachable.
    if (results[2].status === 'fulfilled') {
      const items = results[2].value.data?.items ?? [];
      setMediamtx(Array.isArray(items) ? items : []);
    } else {
      setMediamtx([]);
    }
    setLoading(false);
    setRefreshTick((t) => t + 1);
  };

  useEffect(() => {
    fetchAll();
    const t = setInterval(fetchAll, pollMs);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pollMs]);

  const setCustomUrl = (droneId: string, url: string | null) => {
    setCustomUrlStored(droneId, url);
    setCustomUrls((prev) => ({ ...prev, [droneId]: url }));
  };

  // Lazily read custom URLs for drones we know about.
  const effectiveCustom = (droneId: string): string | null => {
    if (droneId in customUrls) return customUrls[droneId];
    const v = getCustomUrl(droneId);
    return v;
  };

  const registryByDrone = new Map<string, VideoStreamRegistry>();
  for (const r of registry) {
    if (r.drone_id) registryByDrone.set(r.drone_id, r);
  }
  const mediamtxByDrone = new Map<string, MediaMtxStream>();
  for (const m of mediamtx) {
    if (m.drone_id) mediamtxByDrone.set(m.drone_id, m);
  }

  const tiles: TileSource[] = useMemo(() => {
    return drones.map((d) =>
      resolveTile(d, registryByDrone, mediamtxByDrone, effectiveCustom(d.drone_id)),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drones, registry, mediamtx, customUrls]);

  return {
    drones,
    tiles,
    loading,
    refreshTick,
    refresh: fetchAll,
    setCustomUrl,
  };
}
