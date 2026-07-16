'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { Card, Tag, Descriptions, Empty, Spin, message } from 'antd';
import { EnvironmentOutlined } from '@ant-design/icons';
import CesiumMap, { Trail, Waypoint, GeoFenceZone } from '@/components/CesiumMap';
import SimControlPanel from '@/components/SimControlPanel';
import MissionEditorPanel, { EditorWaypoint } from '@/components/MissionEditorPanel';
import TrajectoryPanel from '@/components/TrajectoryPanel';
import CameraFollowToggle from '@/components/CameraFollowToggle';
import GlobalEventStream from '@/components/GlobalEventStream';
import UOMPanel from '@/components/UOMPanel';
import MetricsPanel from '@/components/MetricsPanel';
import RemoteIDOverlay from '@/components/RemoteIDOverlay';
import { api, getDrones } from '@/lib/api';

interface Drone {
  id?: string;
  sn?: string;
  model?: string;
  status?: string;
  online?: boolean;
  [k: string]: any;
}

function apiBase(): string {
  const env = (process.env.NEXT_PUBLIC_API_BASE_URL as string | undefined) || '';
  if (env) return env.replace(/\/$/, '');
  if (typeof window !== 'undefined') {
    return `${window.location.protocol}//${window.location.hostname}:8000/api/v1`;
  }
  return 'http://localhost:8000/api/v1';
}

export default function LiveMapPage() {
  const [drones, setDrones] = useState<Drone[]>([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<{ droneId: string; telemetry: any } | null>(null);

  // Mission-editor state
  const [drawing, setDrawing] = useState(false);
  const [wps, setWps] = useState<EditorWaypoint[]>([]);
  const [defaultAlt, setDefaultAlt] = useState<number>(100);
  const [editorSysid, setEditorSysid] = useState<number>(1);
  const [trails, setTrails] = useState<Trail[]>([]);
  const [following, setFollowing] = useState<boolean>(false);
  const [zones, setZones] = useState<GeoFenceZone[]>([]);

  useEffect(() => {
    (async () => {
      try {
        const r = await api.get<{ zones: GeoFenceZone[] }>('/geofence/zones');
        setZones(r.data.zones);
      } catch (err) {
        console.warn('[live] getZones failed', err);
      }
    })();
  }, []);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const data = await getDrones();
        const list: Drone[] = Array.isArray(data) ? data : data?.items || [];
        setDrones(list);
      } catch (err: any) {
        console.warn('[live] getDrones failed, falling back to demo drones', err);
        setDrones([
          { id: '1', sn: 'FAKE-01', model: 'FakeDrone', status: 'online', online: true },
          { id: '2', sn: 'FAKE-02', model: 'FakeDrone', status: 'online', online: true },
        ]);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const onlineDrones = useMemo(
    () =>
      drones.filter(
        (d) =>
          d.online === true ||
          d.status === 'online' ||
          d.status === 'flying' ||
          d.status === 'idle'
      ),
    [drones]
  );

  const droneIds = useMemo(
    () => onlineDrones.map((d) => d.id || d.sn).filter(Boolean) as string[],
    [onlineDrones]
  );

  const onMapClick = (lat: number, lng: number) => {
    if (!drawing) return;
    setWps((prev) => [...prev, { lat, lng, alt: defaultAlt }]);
  };

  const editorWaypoints: Waypoint[] = useMemo(
    () => wps.map((w, i) => ({ seq: i + 1, lat: w.lat, lng: w.lng, alt: w.alt })),
    [wps]
  );

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        marginTop: 56,
        marginLeft: 220,
        background: '#0b1220',
      }}
    >
      <GlobalEventStream />
      <Spin spinning={loading} style={{ height: '100%' }}>
        {droneIds.length === 0 && !loading ? (
          <div
            style={{
              height: '100%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Empty description={<span style={{ color: '#8b949e' }}>暂无在线设备</span>} />
          </div>
        ) : (
          <div style={{ position: 'relative', width: '100%', height: '100%' }}>
            <CesiumMap
              droneIds={droneIds}
              waypoints={editorWaypoints}
              trails={trails}
              zones={zones}
              height="100%"
              followPrimary={following}
              onDroneClick={(droneId, telemetry) => setSelected({ droneId, telemetry })}
              onMapClick={onMapClick}
            />

            <CameraFollowToggle
              followId={selected?.droneId || droneIds[0]}
              onToggle={setFollowing}
            />

            <UOMPanel
              defaultArea={
                editorWaypoints.length >= 3
                  ? editorWaypoints.map((w) => [w.lng, w.lat])
                  : undefined
              }
            />

            <MetricsPanel />

            <RemoteIDOverlay
              ownFleet={
                new Set(
                  (drones ?? []).map((d: any) => String(d.droneId ?? d.id ?? ''))
                )
              }
            />

            <SimControlPanel selectedDroneId={selected?.droneId} />

            <MissionEditorPanel
              sysid={editorSysid}
              waypoints={wps}
              onChange={setWps}
              drawing={drawing}
              onToggleDrawing={(d) => {
                setDrawing(d);
                if (d) message.info('绘制模式开启：在地图上点击添加航点');
              }}
              defaultAlt={defaultAlt}
              onDefaultAltChange={setDefaultAlt}
              apiBase={apiBase()}
            />

            <TrajectoryPanel
              droneIds={droneIds}
              apiBase={apiBase()}
              onTrailsUpdate={setTrails}
            />

            {/* Bottom-center status bar */}
            <div
              style={{
                position: 'absolute',
                bottom: 16,
                left: '50%',
                transform: 'translateX(-50%)',
                background: 'rgba(13, 17, 23, 0.85)',
                border: '1px solid #21262d',
                borderRadius: 6,
                padding: '8px 16px',
                color: '#e6edf3',
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                zIndex: 10,
              }}
            >
              <EnvironmentOutlined style={{ color: '#51cf66' }} />
              <span>
                <strong style={{ fontSize: 18 }}>{droneIds.length}</strong>
                <span style={{ marginLeft: 6, color: '#8b949e' }}>台在线</span>
              </span>
              {wps.length > 0 && (
                <>
                  <span style={{ color: '#30363d' }}>|</span>
                  <span>
                    ✏️ 待派发 <strong style={{ color: '#58a6ff' }}>{wps.length}</strong> 航点
                  </span>
                </>
              )}
            </div>

            {/* Selected drone popup */}
            {selected && (
              <Card
                title={
                  <span>
                    <Tag color="green">在线</Tag>
                    {selected.droneId}
                  </span>
                }
                size="small"
                extra={
                  <a onClick={() => setSelected(null)} style={{ color: '#8b949e' }}>
                    关闭
                  </a>
                }
                style={{
                  position: 'absolute',
                  bottom: 70,
                  left: 16,
                  width: 300,
                  background: 'rgba(13, 17, 23, 0.9)',
                  border: '1px solid #21262d',
                  zIndex: 10,
                }}
                headStyle={{ color: '#e6edf3', borderBottom: '1px solid #21262d' }}
                bodyStyle={{ color: '#e6edf3' }}
              >
                <Descriptions column={1} size="small" labelStyle={{ color: '#8b949e' }}>
                  <Descriptions.Item label="纬度">
                    {selected.telemetry?.lat != null ? selected.telemetry.lat.toFixed(6) : '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="经度">
                    {selected.telemetry?.lng != null ? selected.telemetry.lng.toFixed(6) : '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="高度">
                    {selected.telemetry?.alt != null ? `${selected.telemetry.alt} m` : '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="速度">
                    {selected.telemetry?.speed != null ? `${selected.telemetry.speed} m/s` : '-'}
                  </Descriptions.Item>
                </Descriptions>
              </Card>
            )}
          </div>
        )}
      </Spin>
    </div>
  );
}
