'use client';

import React, { useEffect, useState } from 'react';
import { Card, Switch, InputNumber, Space, Tag } from 'antd';
import { HistoryOutlined } from '@ant-design/icons';
import type { Trail } from './CesiumMap';

interface Props {
  droneIds: string[];
  apiBase: string;
  onTrailsUpdate: (trails: Trail[]) => void;
}

/**
 * Bottom-left "轨迹" toggle. When enabled, polls /api/v1/trajectory/{id}
 * for each drone every N seconds and hands the trails up to CesiumMap.
 */
export default function TrajectoryPanel({ droneIds, apiBase, onTrailsUpdate }: Props) {
  const [enabled, setEnabled] = useState(false);
  const [seconds, setSeconds] = useState<number>(300);
  const [pointCounts, setPointCounts] = useState<Record<string, number>>({});

  useEffect(() => {
    if (!enabled || droneIds.length === 0) {
      onTrailsUpdate([]);
      setPointCounts({});
      return;
    }

    let alive = true;

    const tick = async () => {
      try {
        const results = await Promise.all(
          droneIds.map(async (id) => {
            const r = await fetch(`${apiBase}/trajectory/${id}?seconds=${seconds}`);
            if (!r.ok) return { id, trail: [] as any[] };
            const j = await r.json();
            return { id, trail: j.trail || [] };
          })
        );

        if (!alive) return;

        const trails: Trail[] = results
          .filter((r) => r.trail.length > 1)
          .map((r) => ({
            droneId: r.id,
            points: r.trail.map((p: any) => ({
              lat: p.lat, lng: p.lng, alt: p.alt ?? 100,
            })),
          }));

        onTrailsUpdate(trails);
        setPointCounts(Object.fromEntries(
          results.map((r) => [r.id, r.trail.length])
        ));
      } catch (e) {
        // Silent — the store may just be empty in dev.
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

  return (
    <Card
      title={
        <span style={{ color: '#e6edf3' }}>
          <HistoryOutlined /> 历史轨迹
        </span>
      }
      size="small"
      style={{
        position: 'absolute',
        bottom: 70,
        right: 16,
        width: 240,
        background: 'rgba(13, 17, 23, 0.92)',
        border: '1px solid #21262d',
        zIndex: 10,
      }}
      headStyle={{ color: '#e6edf3', borderBottom: '1px solid #21262d', padding: '0 12px' }}
      bodyStyle={{ padding: 10 }}
    >
      <Space direction="vertical" size="small" style={{ width: '100%' }}>
        <Space>
          <Switch
            checked={enabled}
            onChange={setEnabled}
            checkedChildren="ON"
            unCheckedChildren="OFF"
          />
          <span style={{ color: '#8b949e', fontSize: 12 }}>
            {enabled ? '实时叠加' : '已关闭'}
          </span>
        </Space>
        {enabled && (
          <>
            <Space>
              <span style={{ color: '#8b949e', fontSize: 12 }}>回溯</span>
              <InputNumber
                size="small"
                value={seconds}
                onChange={(v) => setSeconds(v || 300)}
                min={30}
                max={3600}
                step={30}
                style={{ width: 80 }}
              />
              <span style={{ color: '#8b949e', fontSize: 12 }}>秒</span>
            </Space>
            <div style={{ fontSize: 11, color: '#8b949e' }}>
              {Object.entries(pointCounts).map(([id, n]) => (
                <Tag key={id} color="orange" style={{ marginBottom: 2 }}>
                  {id}: {n} 点
                </Tag>
              ))}
            </div>
          </>
        )}
      </Space>
    </Card>
  );
}
