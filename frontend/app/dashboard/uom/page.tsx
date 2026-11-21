'use client';

import { useCallback, useEffect, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import {
  ConfigProvider, theme as antdTheme, Button, Tag, Input, InputNumber,
  Select, Modal, Alert, Spin, Empty, Tooltip,
} from 'antd';
import {
  SafetyCertificateOutlined, ReloadOutlined, AuditOutlined,
  CheckCircleOutlined, CloseCircleOutlined, ClockCircleOutlined,
  DeleteOutlined, ExportOutlined, CompassOutlined, PlusOutlined,
  KeyOutlined, LinkOutlined,
} from '@ant-design/icons';
import {
  getUomStatus, getUomStates, listUomReports, approveUomReport,
  rejectUomReport, cancelUomReport, expireUomReports, checkUomAirspace,
  createUomReport, uomReportsCsvUrl,
  type UomStatus, type UomStates, type UomReport, type UomVerdict,
} from '@/lib/api';

// UOM 合规面板：模式/凭据状态、上报状态机、报告审核、空域快查。
// 状态枚举与统计全部来自后端 /uom/states，页面不硬编码状态清单。

const DARK_BG = '#0b1220';
const PANEL_BG = '#111a2c';
const PANEL_BORDER = '#1c2942';
const ACCENT = '#2b7fff';
const CYAN = '#36cfc9';

const pageStyle: CSSProperties = {
  minHeight: '100vh', background: DARK_BG, color: '#dbe6f5', padding: 24,
};
const panelStyle: CSSProperties = {
  background: PANEL_BG, border: `1px solid ${PANEL_BORDER}`,
  borderRadius: 10, padding: 16,
};
const gridStyle: CSSProperties = {
  display: 'grid', gap: 16,
  gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
};

const STATE_COLOR: Record<string, string> = {
  draft: 'default', pending: 'processing', approved: 'success',
  rejected: 'error', cancelled: 'default', expired: 'warning',
};
const STATE_LABEL: Record<string, string> = {
  draft: '草稿', pending: '待审', approved: '已批准',
  rejected: '已驳回', cancelled: '已取消', expired: '已过期',
};
const MODE_LABEL: Record<string, string> = {
  mock: 'Mock 演示', live: 'Live 正式', proxy: 'Proxy 网关',
};

function Panel({
  title, icon, extra, children,
}: {
  title: string; icon: ReactNode; extra?: ReactNode; children: ReactNode;
}) {
  return (
    <div style={panelStyle}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
        <span style={{ color: CYAN, fontSize: 16 }}>{icon}</span>
        <span style={{ fontWeight: 600, fontSize: 14 }}>{title}</span>
        <span style={{ flex: 1 }} />
        {extra}
      </div>
      {children}
    </div>
  );
}

function KV({ k, v, ok }: { k: string; v: ReactNode; ok?: boolean }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, padding: '5px 0', borderBottom: '1px solid #1b2840' }}>
      <span style={{ color: '#8ba3c7', fontSize: 12 }}>{k}</span>
      <span style={{ fontSize: 12, color: ok === undefined ? '#dbe6f5' : ok ? '#52c41a' : '#faad14' }}>{v}</span>
    </div>
  );
}

function fmtTs(ts?: number | null) {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  return Number.isNaN(d.getTime()) ? String(ts) : d.toLocaleString('zh-CN', { hour12: false });
}

export default function UomPanelPage() {
  const [status, setStatus] = useState<UomStatus | null>(null);
  const [states, setStates] = useState<UomStates | null>(null);
  const [reports, setReports] = useState<UomReport[]>([]);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [verdict, setVerdict] = useState<UomVerdict | null>(null);
  const [air, setAir] = useState({ lat: 22.82, lng: 108.32, altitude_m: 80 });
  const [rejectTarget, setRejectTarget] = useState<UomReport | null>(null);
  const [rejectReason, setRejectReason] = useState('空域临时管制');
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState({
    operator_id: 'org-12309', pilot_name: '巡逻飞手', aircraft_reg: 'UAS-12309-01',
    purpose: '12309 辖区巡检', max_alt_m: 120,
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, st, rp] = await Promise.all([
        getUomStatus(), getUomStates(),
        listUomReports(statusFilter ? { status: statusFilter } : undefined),
      ]);
      setStatus(s); setStates(st); setReports(rp.reports);
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => { load().catch(() => {}); }, [load]);

  const act = async (fn: () => Promise<unknown>, msg: string) => {
    setLoading(true);
    try {
      await fn();
      await load();
    } catch (e: any) {
      Modal.error({ title: '操作失败', content: e?.response?.data?.detail || String(e) });
    } finally {
      setLoading(false);
    }
    void msg;
  };

  const onCheck = async () => {
    setLoading(true);
    try {
      setVerdict(await checkUomAirspace(air));
    } catch (e: any) {
      Modal.error({ title: '空域查询失败', content: e?.response?.data?.detail || String(e) });
    } finally {
      setLoading(false);
    }
  };

  const onCreate = async () => {
    const now = Math.floor(Date.now() / 1000);
    await act(() => createUomReport({
      ...form,
      area_polygon: [
        [108.28, 22.78], [108.36, 22.78], [108.36, 22.86], [108.28, 22.86],
      ],
      start_ts: now + 60, end_ts: now + 3660,
    }), '上报已提交');
    setCreateOpen(false);
  };

  return (
    <ConfigProvider theme={{ algorithm: antdTheme.darkAlgorithm, token: { colorPrimary: ACCENT } }}>
      <div style={pageStyle}>
        <Spin spinning={loading}>
          <div style={{ maxWidth: 1400, margin: '0 auto' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
              <SafetyCertificateOutlined style={{ color: CYAN, fontSize: 26 }} />
              <div>
                <h2 style={{ margin: 0, fontSize: 22 }}>UOM 合规上报</h2>
                <div style={{ color: '#8ba3c7', fontSize: 12 }}>
                  民航局无人机监管平台 · 配置驱动三模式 · 上报状态机全景
                </div>
              </div>
              <span style={{ flex: 1 }} />
              <Button icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新建上报</Button>
              <Button icon={<ReloadOutlined />} onClick={() => load().catch(() => {})}>刷新</Button>
            </div>

            {status?.mode === 'mock' && (
              <Alert type="warning" showIcon style={{ marginBottom: 16 }}
                message="当前为 Mock 演示模式"
                description={status.note} />
            )}

            <div style={gridStyle}>
              {/* 模式与凭据 */}
              <Panel title="链路模式与凭据" icon={<KeyOutlined />}>
                {status && <>
                  <KV k="运行模式" v={<Tag color={status.mode === 'mock' ? 'blue' : 'green'}>{MODE_LABEL[status.mode] || status.mode}</Tag>} />
                  <KV k="配置版本" v={status.config_version || '—'} />
                  <KV k="签名算法" v={status.signature.algorithm || '—'} />
                  <KV k="时间容忍" v={status.signature.max_skew_s != null ? `${status.signature.max_skew_s}s` : '—'} />
                  <KV k="Base URL" v={status.base_url_env || '—'} ok={status.base_url_set} />
                  <KV k="AK" v={status.ak_env || '—'} ok={status.ak_set} />
                  <KV k="SK" v={status.sk_env || '—'} ok={status.sk_set} />
                  <div style={{ marginTop: 10, color: '#5f7699', fontSize: 11 }}>
                    凭据仅从环境变量读取，页面不回显明文。
                  </div>
                </>}
              </Panel>

              {/* 状态机 */}
              <Panel title="上报状态机" icon={<AuditOutlined />}
                extra={<Tooltip title="到期宽限 / 自动审批延迟 / 高度上限均来自后端配置">
                  <Button size="small" icon={<ClockCircleOutlined />}
                    onClick={() => act(() => expireUomReports(), '到期对账完成')}>
                    到期对账
                  </Button>
                </Tooltip>}>
                {states && <>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
                    {states.states.map((s) => (
                      <Tooltip key={s} title={`${s} · ${states.counts[s] ?? 0} 条`}>
                        <Tag color={STATE_COLOR[s] || 'default'} style={{ margin: 0, padding: '4px 10px' }}>
                          {STATE_LABEL[s] || s} {states.counts[s] ?? 0}
                        </Tag>
                      </Tooltip>
                    ))}
                  </div>
                  <KV k="上报总数" v={states.total} />
                  <KV k="到期宽限" v={`${states.config.expire_after_end_s}s`} />
                  <KV k="审批延迟" v={`${states.config.approval_delay_s}s`} />
                  <KV k="自动审批" v={states.config.auto_approve ? '开启' : '关闭'} ok={states.config.auto_approve} />
                  <KV k="高度上限" v={`${states.config.max_alt_m}m`} />
                </>}
              </Panel>

              {/* 空域快查 */}
              <Panel title="适飞空域快查" icon={<CompassOutlined />}>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
                  <InputNumber value={air.lat} onChange={(v) => setAir({ ...air, lat: Number(v) })}
                    step={0.01} placeholder="纬度" style={{ width: 110 }} />
                  <InputNumber value={air.lng} onChange={(v) => setAir({ ...air, lng: Number(v) })}
                    step={0.01} placeholder="经度" style={{ width: 110 }} />
                  <InputNumber value={air.altitude_m} onChange={(v) => setAir({ ...air, altitude_m: Number(v) })}
                    min={0} placeholder="高度 m" style={{ width: 100 }} />
                  <Button type="primary" onClick={onCheck}>查询</Button>
                </div>
                {verdict ? (
                  <>
                    <div style={{ marginBottom: 8 }}>
                      <Tag color={verdict.allowed ? 'success' : 'error'} icon={verdict.allowed ? <CheckCircleOutlined /> : <CloseCircleOutlined />}>
                        {verdict.allowed ? '可飞' : '不可飞'}
                      </Tag>
                      <Tag>{verdict.zone_type}</Tag>
                      {verdict.ceiling_m != null && <Tag>限高 {verdict.ceiling_m}m</Tag>}
                    </div>
                    <div style={{ color: '#8ba3c7', fontSize: 12 }}>{verdict.reason}</div>
                    {verdict.references.length > 0 && (
                      <div style={{ marginTop: 6, color: '#5f7699', fontSize: 11 }}>
                        <LinkOutlined /> {verdict.references.join(' · ')}
                      </div>
                    )}
                  </>
                ) : <div style={{ color: '#5f7699', fontSize: 12 }}>输入坐标与高度，查询适飞判定。</div>}
              </Panel>
            </div>

            {/* 报告列表 */}
            <div style={{ ...panelStyle, marginTop: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
                <AuditOutlined style={{ color: CYAN, fontSize: 16 }} />
                <span style={{ fontWeight: 600, fontSize: 14 }}>上报记录</span>
                <Select allowClear placeholder="按状态筛选" value={statusFilter}
                  onChange={setStatusFilter} style={{ width: 140 }}
                  options={states?.states.map((s) => ({ value: s, label: STATE_LABEL[s] || s })) || []} />
                <span style={{ flex: 1 }} />
                <a href={uomReportsCsvUrl({ status: statusFilter })} download>
                  <Button size="small" icon={<ExportOutlined />}>导出 CSV</Button>
                </a>
              </div>
              {reports.length === 0 ? (
                <Empty description="暂无上报记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              ) : (
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                    <thead>
                      <tr style={{ color: '#8ba3c7', textAlign: 'left' }}>
                        {['ID', '单位', '飞手', '机体', '用途', '高度', '时段', '状态', '审批号', '操作'].map((h) => (
                          <th key={h} style={{ padding: '8px 10px', borderBottom: '1px solid #263555', whiteSpace: 'nowrap' }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {reports.map((r) => (
                        <tr key={r.id}>
                          <td style={{ padding: '8px 10px', borderBottom: '1px solid #1b2840', fontFamily: 'monospace' }}>{r.id.slice(0, 8)}</td>
                          <td style={{ padding: '8px 10px', borderBottom: '1px solid #1b2840' }}>{r.operator_id}</td>
                          <td style={{ padding: '8px 10px', borderBottom: '1px solid #1b2840' }}>{r.pilot_name}</td>
                          <td style={{ padding: '8px 10px', borderBottom: '1px solid #1b2840' }}>{r.aircraft_reg}</td>
                          <td style={{ padding: '8px 10px', borderBottom: '1px solid #1b2840' }}>{r.purpose}</td>
                          <td style={{ padding: '8px 10px', borderBottom: '1px solid #1b2840' }}>{r.max_alt_m}m</td>
                          <td style={{ padding: '8px 10px', borderBottom: '1px solid #1b2840', whiteSpace: 'nowrap' }}>{fmtTs(r.start_ts)} ~ {fmtTs(r.end_ts)}</td>
                          <td style={{ padding: '8px 10px', borderBottom: '1px solid #1b2840' }}>
                            <Tag color={STATE_COLOR[r.status] || 'default'}>{STATE_LABEL[r.status] || r.status}</Tag>
                          </td>
                          <td style={{ padding: '8px 10px', borderBottom: '1px solid #1b2840', fontFamily: 'monospace' }}>{r.approval_code || '—'}</td>
                          <td style={{ padding: '8px 10px', borderBottom: '1px solid #1b2840', whiteSpace: 'nowrap' }}>
                            {r.status === 'pending' && <>
                              <Button size="small" type="link" icon={<CheckCircleOutlined />}
                                onClick={() => act(() => approveUomReport(r.id), '已批准')}>批准</Button>
                              <Button size="small" type="link" danger icon={<CloseCircleOutlined />}
                                onClick={() => { setRejectTarget(r); }}>驳回</Button>
                            </>}
                            {['draft', 'pending'].includes(r.status) && (
                              <Button size="small" type="link" icon={<DeleteOutlined />}
                                onClick={() => act(() => cancelUomReport(r.id), '已取消')}>取消</Button>
                            )}
                            {!['draft', 'pending'].includes(r.status) && <span style={{ color: '#5f7699' }}>—</span>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </Spin>

        <Modal title="新建上报" open={createOpen} onCancel={() => setCreateOpen(false)}
          onOk={onCreate} okText="提交">
          <div style={{ display: 'grid', gap: 10 }}>
            {([
              ['operator_id', '单位 ID'], ['pilot_name', '飞手'],
              ['aircraft_reg', '机体注册号'], ['purpose', '用途'],
            ] as const).map(([k, label]) => (
              <div key={k}>
                <div style={{ color: '#8ba3c7', fontSize: 12, marginBottom: 4 }}>{label}</div>
                <Input value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
              </div>
            ))}
            <div>
              <div style={{ color: '#8ba3c7', fontSize: 12, marginBottom: 4 }}>最大高度 (m)</div>
              <InputNumber value={form.max_alt_m} min={1} max={500}
                onChange={(v) => setForm({ ...form, max_alt_m: Number(v) })} style={{ width: '100%' }} />
            </div>
            <div style={{ color: '#5f7699', fontSize: 11 }}>
              区域与时间窗使用 12309 预设值，提交后进入待审。
            </div>
          </div>
        </Modal>

        <Modal title="驳回上报" open={!!rejectTarget} onCancel={() => setRejectTarget(null)}
          onOk={() => {
            if (rejectTarget) {
              void act(() => rejectUomReport(rejectTarget.id, rejectReason), '已驳回')
                .then(() => setRejectTarget(null));
            }
          }} okText="确认驳回" okButtonProps={{ danger: true }}>
          <div style={{ color: '#8ba3c7', fontSize: 12, marginBottom: 6 }}>驳回理由</div>
          <Input value={rejectReason} onChange={(e) => setRejectReason(e.target.value)} />
        </Modal>
      </div>
    </ConfigProvider>
  );
}
