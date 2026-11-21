'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { ConfigProvider, theme as antdTheme, Tag } from 'antd';
import {
  ApiOutlined,
  BellOutlined,
  ClockCircleOutlined,
  RocketOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import CesiumMap, { Trail } from '@/components/CesiumMap';
import { api } from '@/lib/api';
import { subscribeTelemetry, TelemetryPayload } from '@/lib/ws';

// ---------------------------------------------------------------------------
// 司空2（FlightHub 2）风格监控大屏：深色驾驶舱 / 左机队树 / 中地图 / 右遥测
// ---------------------------------------------------------------------------

const DARK_BG = '#0b1220';
const PANEL_BG = '#111a2c';
const ACCENT = '#2b7fff';
const GREEN = '#52c41a';
const AMBER = '#faad14';
const RED = '#ff4d4f';

type Stats = {
  total_drones: number;
  online_drones: number;
  flight_logs_24h: number;
  missions_today: number;
  pending_approvals: number;
  status_dist: Record<string, number>;
  per_drone: { drone_id: string; sn: string; online: boolean }[];
};

type FleetItem = {
  drone_id: string;
  sn: string;
  online: boolean;
  battery?: number;
  alt?: number;
  speed?: number;
  mode?: string;
  lastTs?: number;
};

const TRAIL_MAX = 120; // 每机保留航迹点数

export default function CockpitPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [fleet, setFleet] = useState<FleetItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selTele, setSelTele] = useState<TelemetryPayload | null>(null);
  const [wsRate, setWsRate] = useState(0); // msgs / 5s
  const [clock, setClock] = useState('--:--:--');
  const trailsRef = useRef<Record<string, { lat: number; lng: number; alt?: number }[]>>({});
  const [trails, setTrails] = useState<Trail[]>([]);
  const rateCounter = useRef(0);

  // ---- stats 轮询 ----
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const res = await api.get<Stats>('/api/v1/drones/stats');
        if (!alive) return;
        setStats(res.data);
        setFleet((prev) => {
          const byId = new Map(prev.map((f) => [f.drone_id, f]));
          return res.data.per_drone.map(
            (d) => byId.get(d.drone_id) ?? { ...d }
          );
        });
        setSelectedId((cur) => cur ?? res.data.per_drone[0]?.drone_id ?? null);
      } catch {
        /* keep last good stats */
      }
    };
    load();
    const t = setInterval(load, 10_000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  // ---- WS 遥测订阅（全部机） ----
  const subscribedRef = useRef(false);
  useEffect(() => {
    if (!fleet.length || subscribedRef.current) return;
    subscribedRef.current = true;
    const subs = fleet.map((d) =>
      subscribeTelemetry(d.drone_id, (msg) => {
        rateCounter.current += 1;
        setFleet((prev) =>
          prev.map((f) =>
            f.drone_id === d.drone_id
              ? {
                  ...f,
                  online: true,
                  battery: typeof msg.battery === 'number' ? msg.battery : f.battery,
                  alt: typeof msg.alt === 'number' ? msg.alt : f.alt,
                  speed: typeof msg.speed === 'number' ? msg.speed : f.speed,
                  mode: (msg.mode as string) || f.mode,
                  lastTs: Date.now(),
                }
              : f
          )
        );
        if (typeof msg.lat === 'number' && typeof msg.lng === 'number') {
          const arr = trailsRef.current[d.drone_id] || (trailsRef.current[d.drone_id] = []);
          arr.push({ lat: msg.lat, lng: msg.lng, alt: msg.alt as number | undefined });
          if (arr.length > TRAIL_MAX) arr.shift();
        }
        setSelTele((cur) =>
          d.drone_id === selectedIdRef.current ? msg : cur
        );
      })
    );
    return () => {
      subs.forEach((s) => s.close());
      subscribedRef.current = false;
    };
  }, [fleet.length]);

  const selectedIdRef = useRef<string | null>(null);
  selectedIdRef.current = selectedId;

  // ---- 航迹节流刷新 + 速率 + 时钟 ----
  useEffect(() => {
    const t1 = setInterval(() => {
      setTrails(
        Object.entries(trailsRef.current)
          .filter(([, pts]) => pts.length >= 2)
          .map(([droneId, points]) => ({ droneId, points }))
      );
    }, 2000);
    const t2 = setInterval(() => {
      setWsRate(rateCounter.current);
      rateCounter.current = 0;
    }, 5000);
    const t3 = setInterval(() => {
      setClock(new Date().toLocaleTimeString('zh-CN', { hour12: false }));
    }, 1000);
    return () => {
      clearInterval(t1);
      clearInterval(t2);
      clearInterval(t3);
    };
  }, []);

  const selected = useMemo(
    () => fleet.find((f) => f.drone_id === selectedId) || null,
    [fleet, selectedId]
  );

  return (
    <ConfigProvider
      theme={{
        algorithm: antdTheme.darkAlgorithm,
        token: { colorPrimary: ACCENT, colorBgContainer: PANEL_BG, borderRadius: 8 },
      }}
    >
      <div
        style={{
          minHeight: 'calc(100vh - 64px)',
          background: DARK_BG,
          margin: -24, // 抵消 antd Content padding，铺满
          padding: 0,
          color: '#e6f0ff',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* ===== 顶部状态栏 ===== */}
        <div
          style={{
            height: 48,
            background: 'linear-gradient(90deg, #0d1526 0%, #101d38 100%)',
            borderBottom: '1px solid #1e2c4a',
            display: 'flex',
            alignItems: 'center',
            gap: 24,
            padding: '0 20px',
            fontSize: 13,
          }}
        >
          <span style={{ fontWeight: 700, fontSize: 15, letterSpacing: 1 }}>
            <ThunderboltOutlined style={{ color: ACCENT }} /> 监控大屏 COCKPIT
          </span>
          <span>
            <RocketOutlined style={{ color: GREEN }} /> 在线机队{' '}
            <b style={{ color: GREEN }}>
              {stats?.online_drones ?? '-'}/{stats?.total_drones ?? '-'}
            </b>
          </span>
          <span>
            <ApiOutlined style={{ color: wsRate > 0 ? GREEN : '#666' }} /> 遥测流{' '}
            <b style={{ color: wsRate > 0 ? GREEN : '#666' }}>{wsRate}/5s</b>
          </span>
          <span>
            <BellOutlined style={{ color: (stats?.pending_approvals ?? 0) > 0 ? AMBER : '#666' }} />{' '}
            待审批 <b>{stats?.pending_approvals ?? '-'}</b>
          </span>
          <span style={{ marginLeft: 'auto', fontFamily: 'monospace' }}>
            <ClockCircleOutlined /> {clock}
          </span>
        </div>

        {/* ===== 主体三栏 ===== */}
        <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
          {/* 左：机队树 */}
          <div
            style={{
              width: 240,
              borderRight: '1px solid #1e2c4a',
              background: PANEL_BG,
              padding: '10px 8px',
              overflowY: 'auto',
            }}
          >
            <div
              style={{
                fontSize: 12,
                color: '#9fb8e0',
                padding: '2px 8px 10px',
                letterSpacing: 1,
              }}
            >
              机队 FLEET
            </div>
            {fleet.map((f) => {
              const active = f.drone_id === selectedId;
              return (
                <div
                  key={f.drone_id}
                  onClick={() => setSelectedId(f.drone_id)}
                  style={{
                    padding: '10px 10px',
                    marginBottom: 6,
                    borderRadius: 8,
                    cursor: 'pointer',
                    background: active ? 'rgba(43,127,255,0.18)' : 'transparent',
                    border: `1px solid ${active ? ACCENT : 'transparent'}`,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                  }}
                >
                  <span
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      background: f.online ? GREEN : '#4a5568',
                      boxShadow: f.online ? `0 0 6px ${GREEN}` : 'none',
                      flexShrink: 0,
                    }}
                  />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div
                      style={{
                        fontFamily: 'monospace',
                        fontSize: 12.5,
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                      }}
                      title={f.drone_id}
                    >
                      {f.sn || f.drone_id}
                    </div>
                    <div style={{ fontSize: 11, color: '#8ca3c7' }}>
                      {f.alt != null ? `${f.alt.toFixed(0)}m ` : ''}
                      {f.mode ? `${f.mode} ` : ''}
                      {f.online ? '在线' : '离线'}
                    </div>
                  </div>
                  {typeof f.battery === 'number' && (
                    <span
                      style={{
                        fontFamily: 'monospace',
                        fontSize: 12,
                        fontWeight: 700,
                        color:
                          f.battery > 50 ? GREEN : f.battery > 25 ? AMBER : RED,
                      }}
                    >
                      {f.battery.toFixed(0)}%
                    </span>
                  )}
                </div>
              );
            })}
          </div>

          {/* 中：地图 */}
          <div style={{ flex: 1, minWidth: 0, position: 'relative' }}>
            <CesiumMap
              droneIds={selectedId ? [selectedId] : fleet.map((f) => f.drone_id)}
              trails={trails}
              followPrimary={!!selectedId}
              onDroneClick={(id) => setSelectedId(id)}
              height="100%"
            />
          </div>

          {/* 右：选中机遥测 */}
          <div
            style={{
              width: 300,
              borderLeft: '1px solid #1e2c4a',
              background: PANEL_BG,
              padding: 16,
              overflowY: 'auto',
            }}
          >
            <div style={{ fontSize: 12, color: '#8ca3c7', letterSpacing: 1, marginBottom: 12 }}>
              实时遥测 TELEMETRY
            </div>
            {selected ? (
              <>
                <div style={{ fontFamily: 'monospace', fontSize: 14, marginBottom: 4 }}>
                  {selected.sn || selected.drone_id}
                </div>
                <div style={{ marginBottom: 16 }}>
                  <Tag color={selected.online ? 'green' : 'default'}>
                    {selected.online ? '在线' : '离线'}
                  </Tag>
                  {selTele?.mode ? <Tag color="blue">{String(selTele.mode)}</Tag> : null}
                </div>
                <BigMetric
                  label="高度 ALT"
                  value={selTele?.alt ?? selected.alt}
                  unit="m"
                  color={ACCENT}
                />
                <BigMetric
                  label="速度 SPD"
                  value={selTele?.speed ?? selected.speed}
                  unit="m/s"
                  color="#13c2c2"
                />
                <BigMetric
                  label="电量 BAT"
                  value={selTele?.battery ?? selected.battery}
                  unit="%"
                  color={
                    (selTele?.battery ?? selected.battery ?? 0) > 25 ? GREEN : RED
                  }
                />
                <div
                  style={{
                    background: 'rgba(43,127,255,0.08)',
                    border: '1px solid #1e2c4a',
                    borderRadius: 8,
                    padding: 12,
                    fontFamily: 'monospace',
                    fontSize: 12,
                    lineHeight: 2,
                    color: '#c6d6f2',
                  }}
                >
                  <div>
                    lat {selTele?.lat != null ? (selTele.lat as number).toFixed(5) : '-'}
                  </div>
                  <div>
                    lng {selTele?.lng != null ? (selTele.lng as number).toFixed(5) : '-'}
                  </div>
                  <div>msg {wsRate > 0 ? 'streaming' : 'idle'}</div>
                </div>
              </>
            ) : (
              <div style={{ color: '#8ca3c7', fontSize: 12 }}>
                左侧选择一台无人机查看实时数据
              </div>
            )}
          </div>
        </div>
      </div>
    </ConfigProvider>
  );
}

function BigMetric({
  label,
  value,
  unit,
  color,
}: {
  label: string;
  value?: number;
  unit: string;
  color: string;
}) {
  return (
    <div
      style={{
        background: 'rgba(43,127,255,0.06)',
        border: '1px solid #1e2c4a',
        borderRadius: 8,
        padding: '10px 14px',
        marginBottom: 10,
      }}
    >
      <div style={{ fontSize: 11, color: '#8ca3c7', letterSpacing: 1 }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 700, color, fontFamily: 'monospace' }}>
        {typeof value === 'number' ? value.toFixed(1) : '--'}
        <span style={{ fontSize: 12, color: '#8ca3c7', marginLeft: 4 }}>{unit}</span>
      </div>
    </div>
  );
}
