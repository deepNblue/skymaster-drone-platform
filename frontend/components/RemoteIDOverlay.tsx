'use client';

/**
 * RemoteIDOverlay — v2.0 民航合规展示层
 *
 * 从 GET /api/v1/remoteid/messages 拉取第三方 UAV 广播位置（ASTM F3411-22a
 * Network RID 模式），叠加到 Cesium 3D 地图上。图标为浅蓝色以区分己方（黄）
 * 与友方/第三方（蓝），点击弹出 UAS 元信息。
 *
 * 使用方式：作为 CesiumMap 的兄弟组件挂在 dashboard/live 页面即可，
 * 内部通过 window 全局 `cesiumViewer` 与地图交互（CesiumMap 已 export）。
 */
import React, { useEffect, useState } from 'react';
import { Card, Badge, Tag, Space, Empty, Divider } from 'antd';
import { RadarChartOutlined, GlobalOutlined } from '@ant-design/icons';
import { api } from '@/lib/api';

interface RIDMessage {
  uas_id: string;
  uas_id_type: number;
  lat: number;
  lng: number;
  alt_m: number;
  track_deg: number;
  speed_ms: number;
  operator_id: string;
  status: string;
  timestamp: number;
}

interface Props {
  /** 己方 drone_id 集合 — 从叠加中排除，避免重复渲染 */
  ownFleet?: Set<string>;
  /** 拉取周期，默认 3s（Remote ID 建议 ≥ 1Hz） */
  pollMs?: number;
}

export default function RemoteIDOverlay({ ownFleet, pollMs = 3000 }: Props) {
  const [messages, setMessages] = useState<RIDMessage[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [lastFetch, setLastFetch] = useState<number>(0);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const r = await api.get('/api/v1/remoteid/messages');
        if (cancelled) return;
        const raw: RIDMessage[] = r.data?.messages ?? [];
        // Filter out own fleet if provided.
        const filtered = ownFleet
          ? raw.filter((m) => !ownFleet.has(m.uas_id))
          : raw;
        setMessages(filtered);
        setLastFetch(Date.now());
        setErr(null);
      } catch (e: any) {
        setErr(e?.message || String(e));
      }
    };
    load();
    const id = setInterval(load, pollMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [ownFleet, pollMs]);

  // Push overlays to the Cesium viewer if available.
  useEffect(() => {
    const viewer = (window as any).cesiumViewer;
    if (!viewer || !viewer.entities) return;

    // Clear previous RID entities
    const toRemove: any[] = [];
    for (const ent of viewer.entities.values) {
      if (ent.id && String(ent.id).startsWith('rid:')) toRemove.push(ent);
    }
    toRemove.forEach((e) => viewer.entities.remove(e));

    // Add fresh RID entities
    const Cesium = (window as any).Cesium;
    if (!Cesium) return;

    for (const m of messages) {
      try {
        viewer.entities.add({
          id: `rid:${m.uas_id}`,
          name: `RID ${m.uas_id}`,
          position: Cesium.Cartesian3.fromDegrees(m.lng, m.lat, m.alt_m || 100),
          point: {
            pixelSize: 12,
            color: Cesium.Color.CYAN.withAlpha(0.85),
            outlineColor: Cesium.Color.WHITE,
            outlineWidth: 2,
            heightReference: Cesium.HeightReference.NONE,
          },
          label: {
            text: `📡 ${m.uas_id}\n${m.operator_id || 'unknown-org'}`,
            font: '11px monospace',
            fillColor: Cesium.Color.CYAN,
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 2,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
            pixelOffset: new Cesium.Cartesian2(0, -14),
            showBackground: true,
            backgroundColor: new Cesium.Color(0, 0, 0, 0.6),
          },
          description: `
            <table>
              <tr><td><b>UAS ID</b></td><td>${m.uas_id}</td></tr>
              <tr><td><b>Operator</b></td><td>${m.operator_id || '-'}</td></tr>
              <tr><td><b>状态</b></td><td>${m.status}</td></tr>
              <tr><td><b>高度</b></td><td>${m.alt_m?.toFixed?.(1) || m.alt_m} m</td></tr>
              <tr><td><b>航向</b></td><td>${m.track_deg?.toFixed?.(0) || m.track_deg}°</td></tr>
              <tr><td><b>速度</b></td><td>${m.speed_ms?.toFixed?.(1) || m.speed_ms} m/s</td></tr>
              <tr><td><b>更新时间</b></td><td>${new Date((m.timestamp || 0) * 1000).toLocaleTimeString()}</td></tr>
            </table>
          `,
        });
      } catch {
        // Non-fatal — viewer may not be fully ready.
      }
    }
  }, [messages]);

  return (
    <Card
      size="small"
      title={
        <Space>
          <RadarChartOutlined style={{ color: '#00c8ff' }} />
          <span>Remote ID · 民航 F3411-22a</span>
          <Badge
            count={messages.length}
            style={{ backgroundColor: '#00c8ff' }}
            showZero
          />
        </Space>
      }
      style={{
        background: 'rgba(13,17,23,0.85)',
        border: '1px solid #21262d',
      }}
      styles={{
        body: { padding: '8px 12px', maxHeight: 200, overflow: 'auto' },
      }}
    >
      {err && (
        <Tag color="red" style={{ marginBottom: 8 }}>
          {err}
        </Tag>
      )}
      {messages.length === 0 ? (
        <Empty
          description="无第三方 UAV"
          image={<GlobalOutlined style={{ fontSize: 28, color: '#7d8590' }} />}
          imageStyle={{ height: 28 }}
        />
      ) : (
        <Space direction="vertical" size={4} style={{ width: '100%' }}>
          {messages.map((m) => (
            <div
              key={m.uas_id}
              style={{
                fontSize: 11,
                fontFamily: 'monospace',
                color: '#e6edf3',
              }}
            >
              <Tag
                color={m.status === 'airborne' ? 'blue' : 'default'}
                style={{ marginRight: 6 }}
              >
                {m.uas_id}
              </Tag>
              <span style={{ color: '#7d8590' }}>
                {m.operator_id || 'unknown'} · alt {m.alt_m?.toFixed?.(0) || 0}m ·{' '}
                {m.speed_ms?.toFixed?.(1) || 0}m/s
              </span>
            </div>
          ))}
        </Space>
      )}
      <Divider style={{ margin: '6px 0' }} />
      <div style={{ fontSize: 10, color: '#7d8590' }}>
        {pollMs / 1000}s 自动刷新 · 最后更新{' '}
        {lastFetch ? new Date(lastFetch).toLocaleTimeString() : '-'}
      </div>
    </Card>
  );
}
