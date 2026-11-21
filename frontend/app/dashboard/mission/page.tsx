'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import {
  ConfigProvider, theme as antdTheme, Button, Select, Tag, Progress,
  Table, Empty, message, Tooltip,
} from 'antd';
import {
  RocketOutlined, CompassOutlined, ReloadOutlined, PlayCircleOutlined,
  PauseCircleOutlined, CaretRightOutlined, CloseCircleOutlined,
  CheckCircleOutlined, WarningOutlined, CloudUploadOutlined, DownloadOutlined,
} from '@ant-design/icons';
import { api } from '@/lib/api';

// DJI 飞行任务页：预设巡逻航线 → 下发 → 进度状态机 → 控制（执行/暂停/恢复/取消）。
// 航线与状态映射均来自后端独立配置文件，前端不硬编码参数。

const DARK_BG = '#0b1220';
const PANEL_BG = '#111a2c';
const PANEL_BORDER = '#1c2942';
const ACCENT = '#2b7fff';
const GREEN = '#52c41a';
const RED = '#ff4d4f';
const CYAN = '#36cfc9';
const AMBER_TEXT = '#ffd591';

type Waypoint = { lat: number; lng: number; alt: number };
type KmzMeta = {
  filename: string;
  wpml_file: string;
  size_bytes: number;
  sha256: string;
  waypoint_count: number;
};
type Route = {
  id: string;
  name: string;
  description: string;
  waypoints: Waypoint[];
};
type Mission = {
  task_id: string;
  flight_id: string;
  drone_sn: string;
  waypoints: Waypoint[];
  idx: number;
  state: string;
  progress: number;
  kmz?: KmzMeta;
  breakpoint?: number;
  breakpoint_source?: string;
  breakpoint_at?: number;
  resume_from?: number;
  message?: string;
  created_at: number;
  updated_at: number;
};
type LogEntry = { ts: string; text: string; level: 'info' | 'ok' | 'warn' | 'err' };

const STATE_META: Record<string, { color: string; label: string }> = {
  prepared: { color: 'blue', label: '已准备' },
  running: { color: 'processing', label: '执行中' },
  paused: { color: 'warning', label: '已暂停' },
  success: { color: 'success', label: '已完成' },
  failed: { color: 'error', label: '失败' },
  cancelled: { color: 'default', label: '已取消' },
};

const panelStyle: CSSProperties = {
  background: PANEL_BG,
  border: `1px solid ${PANEL_BORDER}`,
  borderRadius: 10,
  padding: 18,
};

function stamp() {
  return new Date().toLocaleTimeString('zh-CN', { hour12: false });
}

export default function MissionPage() {
  const [aircraft, setAircraft] = useState<string[]>([]);
  const [selected, setSelected] = useState('');
  const [routes, setRoutes] = useState<Route[]>([]);
  const [routeId, setRouteId] = useState('');
  const [missions, setMissions] = useState<Mission[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const log = useCallback((text: string, level: LogEntry['level'] = 'info') => {
    setLogs((prev) => [{ ts: stamp(), text, level }, ...prev].slice(0, 80));
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const s = await api.get('/api/v1/dji/status');
        const list: string[] = s.data?.aircraft || [];
        setAircraft(list);
        if (list.length) setSelected((prev) => prev || list[0]);
      } catch (e: any) {
        setErr(e?.response?.data?.detail || '无法获取飞行器列表');
      }
      try {
        const r = await api.get('/api/v1/dji/mission/routes');
        const list: Route[] = r.data?.routes || [];
        setRoutes(list);
        if (list.length) setRouteId((prev) => prev || list[0].id);
      } catch (e: any) {
        setErr(e?.response?.data?.detail || '无法获取预设航线');
      }
    })();
  }, []);

  useEffect(() => {
    if (!selected) return;
    let alive = true;
    const poll = async () => {
      try {
        const { data } = await api.get('/api/v1/dji/mission/status', {
          params: { drone_sn: selected },
        });
        if (!alive) return;
        setMissions(data?.missions || []);
        setErr('');
      } catch (e: any) {
        if (alive) setErr(e?.response?.data?.detail || '任务服务不可用');
      }
    };
    poll();
    const t = setInterval(poll, 1500);
    return () => { alive = false; clearInterval(t); };
  }, [selected]);

  const route = useMemo(
    () => routes.find((r) => r.id === routeId) || null,
    [routes, routeId],
  );

  const doPrepare = async () => {
    if (!selected || !route) {
      message.warning('请先选择飞行器和航线');
      return;
    }
    setBusy(true);
    try {
      const { data } = await api.post('/api/v1/dji/mission/prepare', {
        drone_sn: selected,
        route_id: route.id,
      });
      log(`下发任务 ${data.task_id} · ${route.name} · ${data.waypoint_count} 航点`, 'ok');
      message.success('任务已下发');
    } catch (e: any) {
      const detail = e?.response?.data?.detail || '任务下发失败';
      log(detail, 'err');
      message.error(detail);
    } finally {
      setBusy(false);
    }
  };

  const doControl = async (taskId: string, action: string) => {
    setBusy(true);
    try {
      await api.post('/api/v1/dji/mission/control', {
        task_id: taskId,
        action,
      });
      const labels: Record<string, string> = {
        execute: '执行', pause: '暂停', resume: '恢复', cancel: '取消',
      };
      log(`${labels[action] || action}任务 ${taskId.slice(0, 8)}`, action === 'cancel' ? 'warn' : 'ok');
      message.success(`已${labels[action] || action}`);
    } catch (e: any) {
      const detail = e?.response?.data?.detail || '指令下发失败';
      log(detail, 'err');
      message.error(detail);
    } finally {
      setBusy(false);
    }
  };

  const downloadKmz = async (taskId: string, filename: string) => {
    try {
      const r = await api.get('/api/v1/dji/mission/kmz', {
        params: { task_id: taskId }, responseType: 'blob',
      });
      const blob = new Blob([r.data], {
        type: 'application/vnd.google-earth.kmz',
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      log(`下载航线文件 ${filename}`, 'ok');
    } catch (e: any) {
      const detail = e?.response?.data?.detail || 'KMZ 下载失败';
      message.error(detail);
      log(detail, 'err');
    }
  };

  const doResumeFrom = async (taskId: string, index?: number) => {
    try {
      setBusy(true);
      const { data } = await api.post('/api/v1/dji/mission/resume-from', {
        task_id: taskId,
        ...(index !== undefined ? { waypoint_index: index } : {}),
      });
      log(`从航点 ${data.resume_from} 续飞 ${taskId.slice(0, 8)}`, 'ok');
      message.success(`已从航点 ${data.resume_from} 续飞`);
    } catch (e: any) {
      const detail = e?.response?.data?.detail || '断点续飞失败';
      message.error(detail);
      log(detail, 'err');
    } finally {
      setBusy(false);
    }
  };

  const wpColumns = [
    {
      title: '#', width: 48,
      render: (_: unknown, __: Waypoint, i: number) => (
        <span style={{ color: '#7f96b8', fontFamily: 'monospace' }}>{String(i + 1).padStart(2, '0')}</span>
      ),
    },
    {
      title: '纬度', dataIndex: 'lat',
      render: (v: number) => <span style={{ fontFamily: 'monospace' }}>{v.toFixed(4)}</span>,
    },
    {
      title: '经度', dataIndex: 'lng',
      render: (v: number) => <span style={{ fontFamily: 'monospace' }}>{v.toFixed(4)}</span>,
    },
    {
      title: '高度', dataIndex: 'alt',
      render: (v: number) => <span style={{ fontFamily: 'monospace' }}>{v.toFixed(0)} m</span>,
    },
  ];

  return (
    <ConfigProvider theme={{ algorithm: antdTheme.darkAlgorithm, token: { colorPrimary: ACCENT } }}>
      <div style={{ background: DARK_BG, color: '#e6edf7', minHeight: '100vh', padding: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 18, flexWrap: 'wrap' }}>
          <RocketOutlined style={{ fontSize: 24, color: CYAN }} />
          <div>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600 }}>DJI 飞行任务</h1>
            <div style={{ color: '#7f96b8', fontSize: 12, marginTop: 4 }}>
              预设巡逻航线 · 任务状态机 · 执行/暂停/恢复/取消
            </div>
          </div>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 10, alignItems: 'center' }}>
            <Select
              value={selected || undefined}
              placeholder="选择飞行器"
              style={{ width: 190 }}
              onChange={(v) => { setSelected(v); log(`切换飞行器 ${v}`); }}
              options={aircraft.map((sn) => ({ value: sn, label: sn }))}
            />
            <Tooltip title="立即刷新任务状态">
              <Button
                icon={<ReloadOutlined />}
                onClick={async () => {
                  try {
                    const { data } = await api.get('/api/v1/dji/mission/status', {
                      params: selected ? { drone_sn: selected } : undefined,
                    });
                    setMissions(data?.missions || []);
                    log('任务状态已刷新');
                  } catch (e: any) {
                    message.error(e?.response?.data?.detail || '刷新失败');
                  }
                }}
              />
            </Tooltip>
          </div>
        </div>

        {err && (
          <div style={{
            ...panelStyle, borderColor: RED, color: '#ffa39e', marginBottom: 16, fontSize: 13,
          }}>
            <WarningOutlined /> {err}
          </div>
        )}

        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'flex-start' }}>
          {/* 左：航线选择 */}
          <div style={{ ...panelStyle, flex: '1 1 380px', minWidth: 340 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
              <CompassOutlined style={{ color: ACCENT }} />
              <span style={{ fontSize: 15, fontWeight: 600 }}>预设巡逻航线</span>
              <Tag style={{ marginLeft: 'auto' }}>{routes.length} 条</Tag>
            </div>

            <div style={{ display: 'grid', gap: 10, marginBottom: 16 }}>
              {routes.map((r) => {
                const active = r.id === routeId;
                return (
                  <div
                    key={r.id}
                    onClick={() => { setRouteId(r.id); log(`选择航线 ${r.name}`); }}
                    style={{
                      border: `1px solid ${active ? CYAN : PANEL_BORDER}`,
                      background: active ? 'rgba(54,207,201,0.08)' : 'rgba(255,255,255,0.02)',
                      borderRadius: 8, padding: '10px 12px', cursor: 'pointer',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontWeight: 600, fontSize: 13 }}>{r.name}</span>
                      <Tag color={active ? 'cyan' : undefined} style={{ marginLeft: 'auto' }}>
                        {r.waypoints.length} 航点
                      </Tag>
                    </div>
                    <div style={{ color: '#7f96b8', fontSize: 11, marginTop: 5, lineHeight: 1.5 }}>
                      {r.description}
                    </div>
                  </div>
                );
              })}
              {!routes.length && <Empty description="暂无预设航线" />}
            </div>

            {route && (
              <>
                <div style={{ color: '#9fb3d1', fontSize: 12, marginBottom: 8 }}>
                  航点序列 · <code style={{ color: CYAN }}>{route.id}</code>
                </div>
                <Table
                  size="small"
                  rowKey="key"
                  columns={wpColumns}
                  dataSource={route.waypoints.map((w, i) => ({ ...w, key: String(i) }))}
                  pagination={false}
                  scroll={{ y: 190 }}
                />
                <Button
                  type="primary"
                  icon={<CloudUploadOutlined />}
                  block
                  loading={busy}
                  disabled={!selected}
                  onClick={doPrepare}
                  style={{ marginTop: 14 }}
                >
                  下发任务到 {selected || '—'}
                </Button>
                <div style={{ color: AMBER_TEXT, fontSize: 11, marginTop: 10, lineHeight: 1.6 }}>
                  ⚠️ 演示航线已避开 12309 核心禁飞区并控制在限高 150m 内。真机执行前仍需完成空域报备与现场净空确认。
                </div>
              </>
            )}
          </div>

          {/* 右：任务状态 */}
          <div style={{ ...panelStyle, flex: '1 1 420px', minWidth: 360 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
              <PlayCircleOutlined style={{ color: GREEN }} />
              <span style={{ fontSize: 15, fontWeight: 600 }}>任务状态</span>
              <Tag style={{ marginLeft: 'auto' }}>{missions.length} 条</Tag>
            </div>

            <div style={{ display: 'grid', gap: 12, maxHeight: 470, overflowY: 'auto' }}>
              {missions.map((m) => {
                const meta = STATE_META[m.state] || { color: 'default', label: m.state };
                const active = m.state === 'running' || m.state === 'paused';
                return (
                  <div key={m.task_id} style={{
                    border: `1px solid ${PANEL_BORDER}`, borderRadius: 8,
                    padding: '12px 14px', background: 'rgba(255,255,255,0.02)',
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                      <code style={{ color: '#9fb3d1', fontSize: 12 }}>
                        {m.task_id.slice(0, 8)}
                      </code>
                      <Tag color={meta.color}>{meta.label}</Tag>
                      <span style={{ marginLeft: 'auto', color: '#7f96b8', fontSize: 11 }}>
                        {m.drone_sn}
                      </span>
                    </div>
                    <Progress
                      percent={Math.round(m.progress || 0)}
                      size="small"
                      strokeColor={m.state === 'failed' ? RED : m.state === 'success' ? GREEN : CYAN}
                    />
                    {m.breakpoint !== undefined && (
                      <div style={{
                        display: 'flex', alignItems: 'center', gap: 8,
                        margin: '6px 0', color: '#9fb3d1', fontSize: 11,
                      }}>
                        <Tag
                          color={m.breakpoint_source === 'device' ? 'cyan'
                            : m.breakpoint_source === 'manual' ? 'purple' : 'blue'}
                          style={{ margin: 0 }}
                        >
                          断点 W{m.breakpoint}/{m.waypoints?.length || 0}
                        </Tag>
                        <span>
                          {m.breakpoint_source === 'device' ? '设备回包'
                            : m.breakpoint_source === 'manual' ? '手动指定' : '本地记录'}
                        </span>
                        {m.breakpoint_at && (
                          <span style={{ color: '#7f96b8' }}>
                            {new Date(m.breakpoint_at * 1000).toLocaleTimeString('zh-CN', { hour12: false })}
                          </span>
                        )}
                        {m.resume_from !== undefined && (
                          <span style={{ color: CYAN }}>已从 W{m.resume_from} 续飞</span>
                        )}
                      </div>
                    )}
                    <div style={{ display: 'flex', gap: 12, color: '#7f96b8', fontSize: 11, marginBottom: 8 }}>
                      <span>航点 {m.idx || 0}/{m.waypoints?.length || 0}</span>
                      <span>flight {m.flight_id?.slice(0, 8)}</span>
                      <span style={{ marginLeft: 'auto' }}>{m.message}</span>
                    </div>
                    {m.kmz && (
                      <div style={{
                        display: 'flex', alignItems: 'center', gap: 8,
                        border: `1px dashed ${PANEL_BORDER}`, borderRadius: 6,
                        padding: '6px 8px', marginBottom: 8,
                        background: 'rgba(54,207,201,0.04)',
                      }}>
                        <Tooltip title={`WPML ${m.kmz.wpml_file} · ${m.kmz.waypoint_count} 航点 · sha256 ${m.kmz.sha256.slice(0, 16)}…`}>
                          <span style={{ color: CYAN, fontSize: 11, fontFamily: 'monospace' }}>
                            <CloudUploadOutlined /> {m.kmz.filename}
                          </span>
                        </Tooltip>
                        <span style={{ color: '#7f96b8', fontSize: 10 }}>
                          {(m.kmz.size_bytes / 1024).toFixed(1)} KB · WPML
                        </span>
                        <Tooltip title="下载 KMZ（可上传至 DJI 平台）">
                          <Button
                            type="link" size="small" icon={<DownloadOutlined />}
                            style={{ marginLeft: 'auto', height: 20, padding: '0 4px', color: CYAN }}
                            onClick={() => downloadKmz(m.task_id, m.kmz!.filename)}
                          >
                            下载
                          </Button>
                        </Tooltip>
                      </div>
                    )}
                    <div style={{ display: 'flex', gap: 8 }}>
                      {m.state === 'prepared' && (
                        <Button size="small" type="primary" icon={<PlayCircleOutlined />}
                          loading={busy} onClick={() => doControl(m.task_id, 'execute')}>
                          执行
                        </Button>
                      )}
                      {active && m.state === 'running' && (
                        <Button size="small" icon={<PauseCircleOutlined />}
                          loading={busy} onClick={() => doControl(m.task_id, 'pause')}>
                          暂停
                        </Button>
                      )}
                      {active && m.state === 'paused' && (
                        <Button size="small" type="primary" icon={<CaretRightOutlined />}
                          loading={busy} onClick={() => doResumeFrom(m.task_id)}>
                          {m.breakpoint !== undefined ? `从 W${m.breakpoint} 续飞` : '恢复'}
                        </Button>
                      )}
                      {m.state !== 'success' && m.state !== 'cancelled' && (
                        <Button size="small" danger icon={<CloseCircleOutlined />}
                          loading={busy} onClick={() => doControl(m.task_id, 'cancel')}>
                          取消
                        </Button>
                      )}
                      {m.state === 'success' && (
                        <span style={{ color: GREEN, fontSize: 12 }}>
                          <CheckCircleOutlined /> 航线执行完成
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
              {!missions.length && (
                <Empty description="暂无任务 · 选择航线后点击「下发任务」" />
              )}
            </div>
          </div>
        </div>

        {/* 日志 */}
        <div style={{ ...panelStyle, marginTop: 16 }}>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 10 }}>操作日志</div>
          <div style={{
            fontFamily: 'monospace', fontSize: 11, lineHeight: 1.9,
            maxHeight: 150, overflowY: 'auto',
          }}>
            {logs.map((l, i) => (
              <div key={`${l.ts}-${i}`} style={{
                color: l.level === 'ok' ? GREEN
                  : l.level === 'err' ? '#ffa39e'
                  : l.level === 'warn' ? '#ffd591' : '#7f96b8',
              }}>
                [{l.ts}] {l.text}
              </div>
            ))}
            {!logs.length && <div style={{ color: '#5e7291' }}>等待操作…</div>}
          </div>
        </div>
      </div>
    </ConfigProvider>
  );
}
