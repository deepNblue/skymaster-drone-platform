'use client';

import { useCallback, useEffect, useState } from 'react';
import type { CSSProperties } from 'react';
import {
  ConfigProvider, theme as antdTheme, Button, Tag, Collapse, Checkbox,
  Progress, Empty, message, Tooltip,
} from 'antd';
import {
  SafetyCertificateOutlined, ReloadOutlined, DownloadOutlined,
  CopyOutlined, CheckCircleOutlined, WarningOutlined, CloseCircleOutlined,
  QuestionCircleOutlined,
} from '@ant-design/icons';
import { api } from '@/lib/api';

// DJI 真机联调核对页：清单来自后端独立配置文件，页面不硬编码核对项。
// 勾选状态保存在浏览器本地，便于逐项过单。

const DARK_BG = '#0b1220';
const PANEL_BG = '#111a2c';
const PANEL_BORDER = '#1c2942';
const ACCENT = '#2b7fff';
const CYAN = '#36cfc9';

type ItemStatus = 'pass' | 'warn' | 'fail' | 'manual';
type ChecklistItem = {
  id: string;
  title: string;
  source: string;
  config_file: string | null;
  value: unknown;
  expected: unknown;
  status: ItemStatus;
  detail: string;
  verify: string;
  secret: boolean;
};
type ChecklistGroup = {
  id: string;
  title: string;
  description: string;
  items: ChecklistItem[];
};
type Report = {
  version: string;
  generated_at: string;
  mode: string;
  connector_mounted: boolean;
  summary: {
    total: number;
    pass: number;
    warn: number;
    fail: number;
    manual: number;
    blocking: string[];
    advisories: string[];
    ready: boolean;
  };
  groups: ChecklistGroup[];
  runtime: Record<string, unknown>;
};

const STATUS_META: Record<ItemStatus, { color: string; label: string; icon: React.ReactNode }> = {
  pass: { color: '#52c41a', label: '通过', icon: <CheckCircleOutlined /> },
  warn: { color: '#faad14', label: '警告', icon: <WarningOutlined /> },
  fail: { color: '#ff4d4f', label: '阻塞', icon: <CloseCircleOutlined /> },
  manual: { color: '#7f96b8', label: '人工核对', icon: <QuestionCircleOutlined /> },
};

const panelStyle: CSSProperties = {
  background: PANEL_BG,
  border: `1px solid ${PANEL_BORDER}`,
  borderRadius: 10,
  padding: 18,
};

const CHECK_KEY = 'dji_preflight_checked';

function loadChecked(): Record<string, boolean> {
  if (typeof window === 'undefined') return {};
  try {
    return JSON.parse(localStorage.getItem(CHECK_KEY) || '{}') || {};
  } catch {
    return {};
  }
}

function displayValue(item: ChecklistItem): string {
  if (item.secret) return String(item.value);
  if (item.value == null || item.value === '') return '(空)';
  if (typeof item.value === 'object') return JSON.stringify(item.value);
  return String(item.value);
}

export default function PreflightPage() {
  const [report, setReport] = useState<Report | null>(null);
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get('/api/v1/dji/preflight');
      setReport(data);
      setErr('');
    } catch (e: any) {
      setErr(e?.response?.data?.detail || '无法读取联调清单');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setChecked(loadChecked());
    load();
  }, [load]);

  const toggle = (id: string, value: boolean) => {
    setChecked((prev) => {
      const next = { ...prev, [id]: value };
      if (typeof window !== 'undefined') {
        localStorage.setItem(CHECK_KEY, JSON.stringify(next));
      }
      return next;
    });
  };

  const fetchMarkdown = async (): Promise<Blob | null> => {
    try {
      const { data } = await api.get('/api/v1/dji/preflight/markdown', {
        responseType: 'blob',
      });
      return new Blob([data], { type: 'text/markdown;charset=utf-8' });
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '导出清单失败');
      return null;
    }
  };

  const download = async () => {
    const blob = await fetchMarkdown();
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'dji-preflight-checklist.md';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const copy = async () => {
    const blob = await fetchMarkdown();
    if (!blob) return;
    const text = await blob.text();
    try {
      await navigator.clipboard.writeText(text);
      message.success('核对清单已复制');
    } catch {
      message.warning('浏览器未授权剪贴板，请改用下载');
    }
  };

  const s = report?.summary;
  const doneManual = report
    ? report.groups.reduce(
        (n, g) => n + g.items.filter((i) => i.status === 'manual' && checked[i.id]).length,
        0,
      )
    : 0;

  return (
    <ConfigProvider theme={{ algorithm: antdTheme.darkAlgorithm, token: { colorPrimary: ACCENT } }}>
      <div style={{ background: DARK_BG, color: '#e6edf7', minHeight: '100vh', padding: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 18, flexWrap: 'wrap' }}>
          <SafetyCertificateOutlined style={{ fontSize: 24, color: CYAN }} />
          <div style={{ flex: 1 }}>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600 }}>DJI 真机联调核对</h1>
            <div style={{ color: '#7f96b8', fontSize: 12, marginTop: 4 }}>
              配置驱动核对清单 · 证书/字段逐项确认 · 本地勾选记录
            </div>
          </div>
          <Tooltip title="重新读取后端配置与运行时状态">
            <Button icon={<ReloadOutlined />} loading={loading} onClick={load}>刷新</Button>
          </Tooltip>
          <Button icon={<CopyOutlined />} onClick={copy}>复制清单</Button>
          <Button type="primary" icon={<DownloadOutlined />} onClick={download}>下载 Markdown</Button>
        </div>

        {err && (
          <div style={{ ...panelStyle, borderColor: '#ff4d4f', color: '#ffa39e', marginBottom: 16 }}>
            {err}
          </div>
        )}

        {!report ? (
          <div style={panelStyle}><Empty description={loading ? '读取中…' : '暂无清单'} /></div>
        ) : (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 14, marginBottom: 18 }}>
              <div style={panelStyle}>
                <div style={{ color: '#7f96b8', fontSize: 12 }}>联调就绪</div>
                <div style={{ marginTop: 8 }}>
                  <Tag color={s?.ready ? 'success' : 'error'} style={{ fontSize: 14, padding: '4px 10px' }}>
                    {s?.ready ? '可开始联调' : `${s?.blocking.length ?? 0} 项阻塞`}
                  </Tag>
                </div>
                <div style={{ color: '#7f96b8', fontSize: 11, marginTop: 8 }}>
                  运行模式 {report.mode} · 连接器{report.connector_mounted ? '已挂载' : '未挂载'}
                </div>
              </div>
              {([
                ['pass', '自动通过'], ['warn', '警告'], ['fail', '阻塞'], ['manual', '人工核对'],
              ] as [ItemStatus, string][]).map(([key, label]) => (
                <div key={key} style={panelStyle}>
                  <div style={{ color: '#7f96b8', fontSize: 12 }}>{label}</div>
                  <div style={{ fontSize: 28, fontWeight: 600, color: STATUS_META[key].color, marginTop: 4 }}>
                    {s?.[key] ?? 0}
                  </div>
                </div>
              ))}
            </div>

            <div style={{ ...panelStyle, marginBottom: 18 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: '#7f96b8' }}>
                <span>核对进度（自动通过 + 已勾选人工项）</span>
                <span>{(s?.pass ?? 0) + doneManual} / {s?.total ?? 0}</span>
              </div>
              <Progress
                percent={Math.round(((s?.pass ?? 0) + doneManual) / Math.max(1, s?.total ?? 1) * 100)}
                strokeColor={CYAN}
                size="small"
                style={{ marginTop: 8 }}
              />
              <div style={{ color: '#5f7699', fontSize: 11, marginTop: 8 }}>
                生成时间 {new Date(report.generated_at).toLocaleString('zh-CN')} ·
                阻塞：{(s?.blocking || []).join('、') || '无'}
              </div>
            </div>

            <Collapse
              defaultActiveKey={report.groups.map((g) => g.id)}
              ghost
              items={report.groups.map((g) => {
                const failed = g.items.filter((i) => i.status === 'fail').length;
                const warned = g.items.filter((i) => i.status === 'warn').length;
                return {
                  key: g.id,
                  label: (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <span style={{ fontWeight: 600 }}>{g.title}</span>
                      <span style={{ color: '#7f96b8', fontSize: 12 }}>{g.items.length} 项</span>
                      {failed > 0 && <Tag color="error">{failed} 阻塞</Tag>}
                      {warned > 0 && <Tag color="warning">{warned} 警告</Tag>}
                    </div>
                  ),
                  children: (
                    <div style={{ display: 'grid', gap: 10, paddingBottom: 8 }}>
                      {g.description && (
                        <div style={{ color: '#7f96b8', fontSize: 12 }}>{g.description}</div>
                      )}
                      {g.items.map((item) => {
                        const meta = STATUS_META[item.status];
                        return (
                          <div key={item.id} style={{
                            ...panelStyle, padding: 14,
                            borderLeft: `3px solid ${meta.color}`,
                          }}>
                            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
                              <Checkbox
                                checked={!!checked[item.id]}
                                onChange={(e) => toggle(item.id, e.target.checked)}
                                style={{ marginTop: 3 }}
                              />
                              <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                                  <span style={{ fontWeight: 600 }}>{item.title}</span>
                                  <Tag color={meta.color} icon={meta.icon}>{meta.label}</Tag>
                                  <code style={{ color: '#5f7699', fontSize: 11 }}>{item.id}</code>
                                </div>
                                <div style={{ marginTop: 8, fontSize: 12, color: '#c2d2ea', wordBreak: 'break-all' }}>
                                  当前值：<code style={{ color: CYAN }}>{displayValue(item)}</code>
                                </div>
                                <div style={{ marginTop: 4, fontSize: 12, color: '#7f96b8' }}>
                                  {item.detail}
                                </div>
                                <div style={{ marginTop: 6, fontSize: 12, color: '#ffd591' }}>
                                  真机核对：{item.verify}
                                </div>
                                {item.config_file && (
                                  <div style={{ marginTop: 6, fontSize: 11, color: '#5f7699' }}>
                                    配置来源 {item.config_file}
                                  </div>
                                )}
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ),
                };
              })}
            />
          </>
        )}
      </div>
    </ConfigProvider>
  );
}
