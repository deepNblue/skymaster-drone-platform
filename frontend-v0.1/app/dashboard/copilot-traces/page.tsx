'use client';

/**
 * T5.6 — Copilot Trace Inspector.
 *
 * A read-only diagnostic surface for admins / power users to peer into
 * what the Copilot agent actually did on a given session:
 *   • List all traces for a session, showing intent + confidence + status
 *   • Expand a trace to see each ReAct step: tool, args, result, latency,
 *     error — indispensable when debugging "why did the agent skip the
 *     RPA dispatch?" or "why did check_airspace return zero?"
 *
 * Not a live console — the copilot-v2 page already covers that. This is
 * a forensic timeline, paired with the T6.7 approval-inbox and the T7.5
 * RPA dispatch buttons, to close the audit loop for AI-driven actions.
 */

import { useCallback, useEffect, useState } from 'react';
import {
  Card, Input, Space, Table, Tag, Typography, Button, Collapse,
  message, Empty, Statistic, Row, Col, Divider,
} from 'antd';
import {
  ExperimentOutlined, ReloadOutlined, HistoryOutlined,
  ThunderboltOutlined, CheckCircleOutlined, CloseCircleOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons';

import {
  listSessionTraces, getTrace,
  type CopilotTrace, type CopilotTraceStep,
} from '@/lib/api';

const { Title, Text } = Typography;

const STATUS_COLOR: Record<string, string> = {
  completed: 'success',
  running: 'processing',
  approved: 'success',
  rejected: 'error',
  pending_approval: 'warning',
  error: 'error',
};

function fmtMs(ms: number | null | undefined): string {
  if (ms == null) return '—';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

function StepRow({ s }: { s: CopilotTraceStep }) {
  const failed = !!s.error;
  return (
    <Card
      size="small"
      style={{
        marginBottom: 8,
        borderLeft: failed ? '3px solid #ff4d4f' : '3px solid #52c41a',
      }}
    >
      <Space wrap>
        <Tag color={failed ? 'red' : 'green'}>
          {failed ? <CloseCircleOutlined /> : <CheckCircleOutlined />} #{s.idx}
        </Tag>
        <Tag color="geekblue">{s.tool || '(no-tool)'}</Tag>
        <Tag icon={<ClockCircleOutlined />}>{fmtMs(s.duration_ms)}</Tag>
        {s.ts && (
          <Text type="secondary" style={{ fontSize: 12 }}>
            {new Date(s.ts).toLocaleTimeString()}
          </Text>
        )}
      </Space>
      <Collapse
        size="small"
        ghost
        style={{ marginTop: 4 }}
        items={[
          {
            key: 'args',
            label: <Text type="secondary">args</Text>,
            children: (
              <pre style={{
                fontSize: 11, background: '#fafafa', padding: 6, margin: 0,
                maxHeight: 160, overflow: 'auto',
              }}>
                {s.args ? JSON.stringify(s.args, null, 2) : '(none)'}
              </pre>
            ),
          },
          {
            key: 'result',
            label: <Text type="secondary">result</Text>,
            children: (
              <pre style={{
                fontSize: 11, background: '#fafafa', padding: 6, margin: 0,
                maxHeight: 220, overflow: 'auto',
              }}>
                {s.result ? JSON.stringify(s.result, null, 2) : '(none)'}
              </pre>
            ),
          },
          ...(failed ? [{
            key: 'err',
            label: <Text type="danger">error</Text>,
            children: (
              <pre style={{
                fontSize: 11, background: '#fff2f0', padding: 6, margin: 0,
                color: '#a8071a', maxHeight: 160, overflow: 'auto',
              }}>
                {s.error}
              </pre>
            ),
          }] : []),
        ]}
      />
    </Card>
  );
}

export default function CopilotTracesPage() {
  const [sessionId, setSessionId] = useState('');
  const [traces, setTraces] = useState<CopilotTrace[]>([]);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, CopilotTrace>>({});

  const load = useCallback(async (sid: string) => {
    if (!sid.trim()) return;
    setLoading(true);
    try {
      const rows = await listSessionTraces(sid.trim());
      setTraces(rows);
      setExpanded({});
    } catch (e: any) {
      message.error(
        '加载失败: ' + (e?.response?.data?.detail ?? e.message),
      );
      setTraces([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      const q = new URLSearchParams(window.location.search).get('session');
      if (q) {
        setSessionId(q);
        load(q);
      }
    }
  }, [load]);

  const onExpand = async (record: CopilotTrace) => {
    if (expanded[record.id]) return;
    try {
      const full = await getTrace(record.id);
      setExpanded((prev) => ({ ...prev, [record.id]: full }));
    } catch (e: any) {
      message.error(
        '展开失败: ' + (e?.response?.data?.detail ?? e.message),
      );
    }
  };

  const summary = {
    total: traces.length,
    completed: traces.filter((t) => t.status === 'completed').length,
    errored: traces.filter((t) => t.status === 'error').length,
    pending: traces.filter((t) => t.status === 'pending_approval').length,
  };

  return (
    <div style={{ padding: 16 }}>
      <div style={{ marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>
          <ExperimentOutlined /> Copilot 追踪检查器
        </Title>
        <Text type="secondary">
          按 session ID 查看 Copilot agent 的 ReAct 步骤明细：工具、参数、结果、耗时、错误。
        </Text>
      </div>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Space.Compact style={{ width: '100%' }}>
          <Input
            placeholder="粘贴 Copilot session ID (UUID)"
            value={sessionId}
            onChange={(e) => setSessionId(e.target.value)}
            onPressEnter={() => load(sessionId)}
            allowClear
          />
          <Button
            type="primary"
            icon={<HistoryOutlined />}
            onClick={() => load(sessionId)}
            loading={loading}
          >
            拉取追踪
          </Button>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => load(sessionId)}
            disabled={!sessionId}
          />
        </Space.Compact>
      </Card>

      {traces.length > 0 && (
        <Card size="small" style={{ marginBottom: 16 }}>
          <Row gutter={16}>
            <Col span={6}><Statistic title="总数" value={summary.total} /></Col>
            <Col span={6}><Statistic title="完成" value={summary.completed} valueStyle={{ color: '#52c41a' }} /></Col>
            <Col span={6}><Statistic title="待审批" value={summary.pending} valueStyle={{ color: '#faad14' }} /></Col>
            <Col span={6}><Statistic title="错误" value={summary.errored} valueStyle={{ color: '#ff4d4f' }} /></Col>
          </Row>
        </Card>
      )}

      {traces.length === 0 && !loading ? (
        <Empty description="无追踪记录" />
      ) : (
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          dataSource={traces}
          expandable={{
            onExpand: (open, record) => open && onExpand(record),
            expandedRowRender: (record) => {
              const full = expanded[record.id];
              if (!full) {
                return (
                  <div style={{ padding: 12, color: '#999' }}>
                    <ThunderboltOutlined /> 加载步骤明细…
                  </div>
                );
              }
              const steps = full.steps ?? [];
              if (steps.length === 0) {
                return (
                  <div style={{ padding: 12 }}>
                    <Text type="secondary">此追踪无步骤（仅意图分类，无工具调用）</Text>
                    {full.output && (
                      <>
                        <Divider style={{ margin: '8px 0' }} />
                        <pre style={{
                          fontSize: 11, background: '#fafafa', padding: 6,
                          maxHeight: 200, overflow: 'auto',
                        }}>
                          {JSON.stringify(full.output, null, 2)}
                        </pre>
                      </>
                    )}
                  </div>
                );
              }
              return (
                <div style={{ padding: 8, background: '#f5f5f5' }}>
                  {steps.map((s) => <StepRow key={s.idx} s={s} />)}
                  {full.output && (
                    <Card size="small" style={{ marginTop: 4 }}>
                      <Text strong style={{ fontSize: 12 }}>final output</Text>
                      <pre style={{
                        fontSize: 11, background: '#fafafa', padding: 6,
                        margin: '4px 0 0 0', maxHeight: 200, overflow: 'auto',
                      }}>
                        {JSON.stringify(full.output, null, 2)}
                      </pre>
                    </Card>
                  )}
                </div>
              );
            },
          }}
          columns={[
            {
              title: '开始时间', dataIndex: 'started_at', width: 160,
              render: (v: string | null) => v
                ? new Date(v).toLocaleString()
                : '—',
            },
            { title: '提示', dataIndex: 'prompt', ellipsis: true },
            {
              title: '意图', dataIndex: 'intent', width: 140,
              render: (v: string | null) => v ? <Tag color="cyan">{v}</Tag> : '—',
            },
            {
              title: '置信度', dataIndex: 'confidence', width: 90,
              render: (v: number | null) => v != null
                ? <Tag>{(v * 100).toFixed(0)}%</Tag>
                : '—',
            },
            {
              title: '状态', dataIndex: 'status', width: 140,
              render: (v: string | null) => v
                ? <Tag color={STATUS_COLOR[v] || 'default'}>{v}</Tag>
                : '—',
            },
            {
              title: '步骤', width: 70,
              render: (_: any, r) => {
                const c = expanded[r.id]?.steps?.length;
                return c != null ? <Tag>{c}</Tag> : <Tag>?</Tag>;
              },
            },
          ]}
          pagination={{ pageSize: 20, showSizeChanger: false }}
        />
      )}
    </div>
  );
}
