'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Card, Switch, InputNumber, Slider, Space, Tag } from 'antd';
import { HistoryOutlined } from '@ant-design/icons';
import type { Trail } from './CesiumMap';

interface Props {
  droneIds: string[];
  apiBase: string;
  onTrailsUpdate: (trails: Trail[]) => void;
}

interface TrackPoint {
  lat: number;
  lng: number;
  alt: number;
  ts: string;
}

/**
 * Bottom-right "历史轨迹 + 回放" panel.
 *
 * Polls /api/v1/drones/{id}/track?seconds=window for each drone, caches the
 * full window (points carry ISO timestamps), then renders only the points
 * with ts <= latest_ts - rewindSeconds. Dragging the slider back in time
 * scrubs the flight replay; slider at 0 means live (full window shown).
 */
export default function TrajectoryPanel({ droneIds, apiBase, onTrailsUpdate }: Props) {
  const [enabled, setEnabled] = useState(false);
  const [seconds, setSeconds] = useState<number>(600);
  const [rewind, setRewind] = useState<number>(0); // 0 = live
  const [latestTsByDrone, setLatestTsByDrone] = useState<Record<string, string>>({});
  const cacheRef = useRef<Record<string, TrackPoint[]>>({});
  const [pointCounts, setPointCounts] = useState<Record<string, number>>({});
  // Keep the freshest cache for the render pass without re-fetch storms.
  const [, forceRender] = useState(0);

  useEffect(() => {
    if (!enabled || droneIds.length === 0) {
      cacheRef.current = {};
      onTrailsUpdate([]);
      setPointCounts({});
      setLatestTsByDrone({});
      return;
    }

    let alive = true;

    const tick = async () => {
      try {
        const results = await Promise.all(
          droneIds.map(async (id) => {
            const { api } = await import('@/lib/api');
            const r = await api.get('/api/v1/drones/' + id + '/track?seconds=' + seconds);
            return {
              id,
              trail: (r.data?.trail || []) as TrackPoint[],
              latest: (r.data?.latest_ts as string) || null,
            };
          })
        );
        if (!alive) return;
        const nextLatest: Record<string, string> = {};
        const nextCounts: Record<string, number> = {};
        for (const r of results) {
          cacheRef.current[r.id] = r.trail;
          nextCounts[r.id] = r.trail.length;
          if (r.latest) nextLatest[r.id] = r.latest;
        }
        setLatestTsByDrone(nextLatest);
        setPointCounts(nextCounts);
        forceRender((n) => n + 1);
      } catch (e) {
        console.warn('[TrajectoryPanel] fetch failed', e);
      }
    };

    tick();
    const id = setInterval(tick, 3000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [enabled, droneIds.join(','), seconds]);

  // Slice the cached window by the rewind slider and hand to CesiumMap.
  useEffect(() => {
    if (!enabled) return;
    const trails: Trail[] = [];
    for (const [id, pts] of Object.entries(cacheRef.current)) {
      let shown = pts;
      if (rewind > 0 && pts.length > 0) {
        const latest = latestTsByDrone[id]
          ? new Date(latestTsByDrone[id]).getTime()
          : new Date(pts[pts.length - 1].ts).getTime();
        const cutoff = latest - rewind * 1000;
        shown = pts.filter((p) => new Date(p.ts).getTime() <= cutoff);
      }
      if (shown.length > 1) {
        trails.push({
          droneId: id,
          points: shown.map((p) => ({ lat: p.lat, lng: p.lng, alt: p.alt })),
        });
      }
    }
    onTrailsUpdate(trails);
  }, [enabled, rewind, latestTsByDrone, pointCounts]);

  const maxRewind = Math.max(0, seconds - 30);

  const rewindLabel = useMemo(() => {
    if (rewind === 0) return '实时';
    const m = Math.floor(rewind / 60);
    const s = rewind % 60;
    return m > 0 ? `回看 -${m}m${s ? s + 's' : ''}` : `回看 -${s}s`;
  }, [rewind]);

  return (
    <Card
      title={
        <span style={{ color: '#e6f0ff' }}>
          <HistoryOutlined /> 历史轨迹
        </span>
      }
      size="small"
      style={{
        position: 'absolute',
        bottom: 70,
        right: 16,
        width: 250,
        background: 'rgba(17, 26, 44, 0.92)',
        border: '1px solid #1e2c4a',
        zIndex: 10,
      }}
      styles={{
        header: { color: '#e6f0ff', borderBottom: '1px solid #1e2c4a', padding: '0 12px' },
        body: { padding: 10 },
      }}
    >
      <Space direction="vertical" size="small" style={{ width: '100%' }}>
        <Space>
          <Switch
            checked={enabled}
            onChange={(v) => {
              setEnabled(v);
              setRewind(0);
            }}
            checkedChildren="ON"
            unCheckedChildren="OFF"
          />
          <span style={{ color: '#9fb8e0', fontSize: 12 }}>
            {enabled ? (rewind > 0 ? '回放模式' : '实时叠加') : '已关闭'}
          </span>
          {enabled && rewind > 0 && (
            <a
              onClick={() => setRewind(0)}
              style={{ fontSize: 12, color: '#2b7fff' }}
            >
              回到实时
            </a>
          )}
        </Space>
        {enabled && (
          <>
            <Space>
              <span style={{ color: '#9fb8e0', fontSize: 12 }}>窗口</span>
              <InputNumber
                size="small"
                value={seconds}
                onChange={(v) => {
                  setSeconds(v || 600);
                  setRewind(0);
                }}
                min={60}
                max={86400}
                step={60}
                style={{ width: 90 }}
              />
              <span style={{ color: '#9fb8e0', fontSize: 12 }}>秒</span>
            </Space>
            <div>
              <div style={{ fontSize: 11, color: '#9fb8e0', marginBottom: 2 }}>
                回放时间轴（拖动回看 · {rewindLabel}）
              </div>
              <Slider
                min={0}
                max={maxRewind}
                step={Math.max(5, Math.round(maxRewind / 120))}
                value={Math.min(rewind, maxRewind)}
                onChange={setRewind}
                tooltip={{
                  formatter: (v) => (v === 0 ? '实时' : `-${v}s 前`),
                }}
                styles={{
                  track: { background: '#2b7fff' },
                  rail: { background: '#1e2c4a' },
                }}
              />
            </div>
            <div style={{ fontSize: 11, color: '#9fb8e0' }}>
              {Object.entries(pointCounts).map(([id, n]) => (
                <Tag key={id} color="blue" style={{ marginBottom: 2 }}>
                  {id.slice(0, 8)}: {n} 点
                </Tag>
              ))}
            </div>
          </>
        )}
      </Space>
    </Card>
  );
}
