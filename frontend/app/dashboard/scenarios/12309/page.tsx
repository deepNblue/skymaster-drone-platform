'use client';

import { useCallback, useEffect, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import {
  ConfigProvider, theme as antdTheme, Button, Tag, Switch, Tooltip,
  Empty, Alert, Spin,
} from 'antd';
import {
  SafetyOutlined, ReloadOutlined, RadarChartOutlined, CompassOutlined,
  AlertOutlined, VideoCameraOutlined, AuditOutlined, FolderOpenOutlined,
  ClockCircleOutlined, ArrowRightOutlined,
} from '@ant-design/icons';
import Link from 'next/link';
import { getScenario12309, type ScenarioBlock, type ScenarioOverview } from './scenarios';

// 12309 防控作战视图：所有范围、阈值、标签来自后端场景配置，页面只负责呈现。
// 各数据块独立降级，MediaMTX / DJI 连接器不可用时不影响整页。

const DARK_BG = '#0b1220';
const PANEL_BG = '#111a2c';
const PANEL_BORDER = '#1c2942';
const ACCENT = '#2b7fff';
const CYAN = '#36cfc9';

const panelStyle: CSSProperties = {
  background: PANEL_BG,
  border: `1px solid ${PANEL_BORDER}`,
  borderRadius: 10,
  padding: 16,
};

const SEVERITY_COLOR: Record<string, string> = {
  high: 'error', medium: 'warning', low: 'blue',
};

const KIND_META: Record<string, { label: string; color: string }> = {
  alert: { label: '告警', color: '#ff4d4f' },
  approval: { label: '审批', color: '#faad14' },
  mission: { label: '任务', color: '#36cfc9' },
  evidence: { label: '取证', color: '#52c41a' },
};

function fmt(value?: string) {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString('zh-CN', { hour12: false });
}

function Block({
  title, icon, block, extra, children,
}: {
  title: string;
  icon: ReactNode;
  block?: ScenarioBlock<any>;
  extra?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div style={panelStyle}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        <span style={{ color: CYAN, fontSize: 16 }}>{icon}</span>
        <span style={{ fontWeight: 600, fontSize: 14 }}>{title}</span>
        {block && <Tag>{block.count}</Tag>}
        <span style={{ flex: 1 }} />
        {extra}
      </div>
      {block && !block.available ? (
        <Alert type="warning" showIcon message="该数据块暂不可用" description={block.reason} />
      ) : children}
    </div>
  );
}

function EmptyHint({ text }: { text: string }) {
  return <div style={{ color: '#5f7699', fontSize: 12, padding: '12px 0' }}>{text}</div>;
}

export default function Scenario12309Page() {
  const [report, setReport] = useState<ScenarioOverview | null>(null);
  const [loading, setLoading] = useState(false);
  const [auto, setAuto] = useState(true);
  const [err, setErr] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getScenario12309();
      setReport(data);
      setErr('');
    } catch (e: any) {
      setErr(e?.response?.data?.detail || '无法读取 12309 场景态势');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!auto) return;
    const timer = setInterval(load, 30000);
    return () => clearInterval(timer);
  }, [auto, load]);

  const meta = report?.meta;
  const grid: CSSProperties = {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(430px, 1fr))',
    gap: 14,
    marginBottom: 14,
  };

  return (
    <ConfigProvider theme={{ algorithm: antdTheme.darkAlgorithm, token: { colorPrimary: ACCENT } }}>
      <div style={{ background: DARK_BG, color: '#e6edf7', minHeight: '100vh', padding: 24 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 18, flexWrap: 'wrap' }}>
          <SafetyOutlined style={{ fontSize: 26, color: CYAN, marginTop: 4 }} />
          <div style={{ flex: 1, minWidth: 260 }}>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600 }}>
              {meta?.name || '12309 防控作战视图'}
            </h1>
            <div style={{ color: '#7f96b8', fontSize: 12, marginTop: 4 }}>
              {meta?.description || '巡逻航线 · 告警 · 视频 · 审批 · 取证闭环'}
            </div>
            <div style={{ color: '#5f7699', fontSize: 11, marginTop: 6 }}>
              {meta?.region?.name} · 责任单位 {meta?.owner} · 限高 {meta?.region?.alt_limit_m}m
              {report?.generated_at && ` · 更新于 ${fmt(report.generated_at)}`}
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ color: '#7f96b8', fontSize: 12 }}>自动刷新 30s</span>
            <Switch size="small" checked={auto} onChange={setAuto} />
            <Tooltip title="立即刷新全部数据块">
              <Button icon={<ReloadOutlined />} loading={loading} onClick={load}>刷新</Button>
            </Tooltip>
          </div>
        </div>

        {err && (
          <div style={{ ...panelStyle, borderColor: '#ff4d4f', marginBottom: 14 }}>
            <Alert type="error" showIcon message={err} />
          </div>
        )}

        {!report ? (
          <div style={{ ...panelStyle, textAlign: 'center', padding: 60 }}>
            <Spin tip="加载场景态势…" />
          </div>
        ) : (
          <>
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(155px, 1fr))',
              gap: 12, marginBottom: 14,
            }}>
              {(meta?.kpis || []).map((kpi) => (
                <div key={kpi.key} style={panelStyle}>
                  <div style={{ color: '#7f96b8', fontSize: 12 }}>{kpi.label}</div>
                  <div style={{ marginTop: 6, fontSize: 28, fontWeight: 600, color: CYAN }}>
                    {report.kpi?.[kpi.key] ?? 0}
                    <span style={{ fontSize: 12, color: '#7f96b8', marginLeft: 4 }}>{kpi.unit}</span>
                  </div>
                </div>
              ))}
            </div>

            <div style={grid}>
              <Block title="巡逻航线" icon={<CompassOutlined />} block={report.routes}
                extra={<Link href="/dashboard/mission" style={{ color: CYAN, fontSize: 12 }}>
                  任务中心 <ArrowRightOutlined />
                </Link>}>
                {report.routes.items.length === 0 ? <EmptyHint text="暂无 12309 预设航线" /> : (
                  <div style={{ display: 'grid', gap: 10 }}>
                    {report.routes.items.map((route) => {
                      const alts = route.waypoints.map((w) => Number(w.alt || 0));
                      return (
                        <div key={route.id} style={{
                          background: '#0d1628', border: '1px solid #1c2942',
                          borderRadius: 8, padding: 12,
                        }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <span style={{ fontWeight: 600 }}>{route.name}</span>
                            <Tag color="cyan">{route.waypoints.length} 航点</Tag>
                          </div>
                          <div style={{ color: '#7f96b8', fontSize: 12, marginTop: 6 }}>
                            {route.description}
                          </div>
                          <div style={{ color: '#5f7699', fontSize: 11, marginTop: 6 }}>
                            {route.id} · 高度 {Math.min(...alts)}–{Math.max(...alts)}m
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </Block>

              <Block title="飞行任务与机队" icon={<RadarChartOutlined />} block={report.missions}>
                <div style={{ color: '#7f96b8', fontSize: 12, marginBottom: 8 }}>
                  在编机体 {report.fleet.count} 架
                  {!report.fleet.available && ` · ${report.fleet.reason || '数据不可用'}`}
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 12 }}>
                  {report.fleet.items.map((d) => (
                    <Tag key={d.id} color={d.status === 'online' ? 'success' : 'default'}>
                      {d.label || d.sn}
                    </Tag>
                  ))}
                  {report.fleet.items.length === 0 && <EmptyHint text="未发现绑定 12309 的机体" />}
                </div>
                {report.missions.items.length === 0 ? <EmptyHint text="当前无执行中任务" /> : (
                  <div style={{ display: 'grid', gap: 8 }}>
                    {report.missions.items.map((m) => (
                      <div key={m.task_id} style={{
                        background: '#0d1628', border: '1px solid #1c2942',
                        borderRadius: 8, padding: 10,
                      }}>
                        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                          <code style={{ color: CYAN, fontSize: 12 }}>{m.task_id}</code>
                          <Tag color={m.state === 'running' ? 'processing' : 'default'}>{m.state}</Tag>
                          <span style={{ color: '#7f96b8', fontSize: 12 }}>{m.drone_sn}</span>
                          <span style={{ marginLeft: 'auto', color: '#c2d2ea', fontSize: 12 }}>
                            {Math.round(Number(m.progress || 0))}%
                          </span>
                        </div>
                        <div style={{ color: '#5f7699', fontSize: 11, marginTop: 6 }}>
                          航点 {m.idx}/{m.waypoint_count}
                          {m.breakpoint != null && ` · 断点 W${m.breakpoint}`}
                          {m.kmz_filename && ` · ${m.kmz_filename}`}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </Block>
            </div>

            <div style={grid}>
              <Block title="异常告警" icon={<AlertOutlined />} block={report.alerts}
                extra={<span style={{ color: '#7f96b8', fontSize: 11 }}>
                  近 {report.alerts.window_minutes || 1440} 分钟
                </span>}>
                {report.alerts.items.length === 0 ? <EmptyHint text="暂无异常发现" /> : (
                  <div style={{ display: 'grid', gap: 8 }}>
                    {report.alerts.items.map((a) => (
                      <div key={a.id} style={{
                        background: '#0d1628', borderLeft: `3px solid ${
                          a.severity === 'high' ? '#ff4d4f' : a.severity === 'medium' ? '#faad14' : '#2b7fff'
                        }`, borderRadius: 6, padding: 10,
                      }}>
                        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                          <span style={{ fontWeight: 600 }}>{a.label}</span>
                          <Tag color={SEVERITY_COLOR[a.severity] || 'blue'}>{a.severity_label}</Tag>
                          {a.open && <Tag color="processing">待处置</Tag>}
                          <span style={{ marginLeft: 'auto', color: '#7f96b8', fontSize: 11 }}>
                            {fmt(a.created_at)}
                          </span>
                        </div>
                        <div style={{ color: '#5f7699', fontSize: 11, marginTop: 6 }}>
                          置信度 {Number(a.confidence || 0).toFixed(2)}
                          {a.lat != null && a.lng != null && ` · ${Number(a.lat).toFixed(4)}, ${Number(a.lng).toFixed(4)}`}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </Block>

              <Block title="视频回传" icon={<VideoCameraOutlined />} block={report.streams}>
                {report.streams.items.length === 0 ? <EmptyHint text="暂无在线流（MediaMTX 未运行或未注册）" /> : (
                  <div style={{ display: 'grid', gap: 8 }}>
                    {report.streams.items.map((s, i) => (
                      <div key={`${s.drone_id}-${i}`} style={{
                        display: 'flex', alignItems: 'center', gap: 10,
                        background: '#0d1628', border: '1px solid #1c2942',
                        borderRadius: 8, padding: 10,
                      }}>
                        <VideoCameraOutlined style={{ color: s.active ? '#52c41a' : '#5f7699' }} />
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: 13 }}>{s.name || s.drone_id}</div>
                          <div style={{ color: '#5f7699', fontSize: 11 }}>{s.drone_id}</div>
                        </div>
                        <Tag color={s.active ? 'success' : 'default'}>{s.active ? '在线' : '离线'}</Tag>
                        {s.drone_id && (
                          <Link href={`/dashboard/streams/${encodeURIComponent(String(s.drone_id))}`}>
                            <Button size="small" type="link">查看</Button>
                          </Link>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </Block>
            </div>

            <div style={grid}>
              <Block title="飞行审批链" icon={<AuditOutlined />} block={report.approvals}>
                {report.approvals.items.length === 0 ? <EmptyHint text="暂无相关审批单" /> : (
                  <div style={{ display: 'grid', gap: 8 }}>
                    {report.approvals.items.map((a) => (
                      <div key={a.id} style={{
                        background: '#0d1628', border: '1px solid #1c2942',
                        borderRadius: 8, padding: 10,
                      }}>
                        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                          <span style={{ fontWeight: 600, flex: 1, minWidth: 120 }}>{a.title}</span>
                          <Tag color={a.open ? 'processing' : 'default'}>{a.status_label}</Tag>
                        </div>
                        <div style={{ color: '#5f7699', fontSize: 11, marginTop: 6 }}>
                          {a.category} · 限高 {a.max_alt_m ?? '—'}m · {fmt(a.start_ts)} 起
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </Block>

              <Block title="取证归档" icon={<FolderOpenOutlined />} block={report.evidence}>
                {report.evidence.items.length === 0 ? <EmptyHint text="暂无 12309 取证场景" /> : (
                  <div style={{ display: 'grid', gap: 8 }}>
                    {report.evidence.items.map((e) => (
                      <div key={e.id} style={{
                        background: '#0d1628', border: '1px solid #1c2942',
                        borderRadius: 8, padding: 10,
                      }}>
                        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                          <span style={{ fontWeight: 600, flex: 1, minWidth: 120 }}>{e.name}</span>
                          <Tag>{e.status}</Tag>
                        </div>
                        <div style={{ color: '#5f7699', fontSize: 11, marginTop: 6 }}>
                          {e.scene_kind} · {e.n_source_images} 张源图 · {e.n_gaussians} 高斯点
                          · {e.asset_count} 份资产 · {fmt(e.created_at)}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </Block>
            </div>

            <div style={panelStyle}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                <ClockCircleOutlined style={{ color: CYAN }} />
                <span style={{ fontWeight: 600, fontSize: 14 }}>态势时间线</span>
                <Tag>{report.timeline.length}</Tag>
              </div>
              {report.timeline.length === 0 ? <EmptyHint text="暂无事件" /> : (
                <div style={{ display: 'grid', gap: 6 }}>
                  {report.timeline.map((e, i) => {
                    const km = KIND_META[e.kind] || { label: e.kind, color: '#7f96b8' };
                    return (
                      <div key={`${e.kind}-${e.id}-${i}`} style={{
                        display: 'flex', alignItems: 'center', gap: 10,
                        borderLeft: `3px solid ${km.color}`, paddingLeft: 10,
                      }}>
                        <Tag color={km.color === '#ff4d4f' ? 'error' : km.color === '#faad14' ? 'warning' : 'default'}>
                          {km.label}
                        </Tag>
                        <span style={{ flex: 1, fontSize: 12 }}>{e.title || e.id}</span>
                        <span style={{ color: '#5f7699', fontSize: 11 }}>{fmt(e.at)}</span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </ConfigProvider>
  );
}
