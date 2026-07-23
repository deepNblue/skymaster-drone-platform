'use client';

/**
 * Copilot Workflow Run History · T10.9 (v2.1 E2.1).
 *
 * Read-only counterpart to the Workflow Editor: browse every /run and
 * /{id}/run audit row for this org, drill into any entry to see the
 * full step trace. No mutation endpoints — history is append-only.
 *
 * Layout:
 *   ┌────────────────────────┬─────────────────────────────┐
 *   │ Left  · list of runs   │  Right · selected run trace │
 *   │ (newest first, filter  │  (steps + result/error JSON)│
 *   │  by workflow_id)       │                             │
 *   └────────────────────────┴─────────────────────────────┘
 *
 * Reused patterns from the editor page:
 *   * statusTag palette (ok/failed/skipped/pending)
 *   * inline JSON viewer with max-height + monospaced font
 *   * message.error for network faults, tags for domain states
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Input,
  List,
  Row,
  Space,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  ReloadOutlined,
  HistoryOutlined,
  FilterOutlined,
} from '@ant-design/icons';

import {
  listWorkflowRunHistory,
  getWorkflowRunHistoryDetail,
  WorkflowRunHistoryEntry,
  WorkflowRunHistoryDetail,
} from '@/lib/copilot_workflows';

const { Title, Text } = Typography;

function statusTag(status: string) {
  const map: Record<string, { color: string; text: string }> = {
    ok: { color: 'green', text: 'OK' },
    failed: { color: 'red', text: 'FAILED' },
    skipped: { color: 'default', text: 'SKIPPED' },
    pending: { color: 'blue', text: 'PENDING' },
  };
  const meta = map[status] ?? { color: 'default', text: status };
  return <Tag color={meta.color}>{meta.text}</Tag>;
}

function fmtTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export default function CopilotWorkflowHistoryPage() {
  const [rows, setRows] = useState<WorkflowRunHistoryEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<WorkflowRunHistoryDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [workflowFilter, setWorkflowFilter] = useState<string>('');

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const list = await listWorkflowRunHistory({
        limit: 100,
        // Only send filter if non-empty & looks UUID-ish.
        workflow_id:
          workflowFilter.trim().length >= 8
            ? workflowFilter.trim()
            : undefined,
      });
      setRows(list);
    } catch (e: any) {
      message.error(`历史加载失败: ${e?.message ?? e}`);
    } finally {
      setLoading(false);
    }
  }, [workflowFilter]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const openRun = useCallback(async (id: string) => {
    setSelectedId(id);
    setDetail(null);
    setDetailLoading(true);
    try {
      const d = await getWorkflowRunHistoryDetail(id);
      setDetail(d);
    } catch (e: any) {
      message.error(`详情加载失败: ${e?.message ?? e}`);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const traceSteps = useMemo(() => {
    if (!detail) return [];
    const t = detail.trace as any;
    return Array.isArray(t?.steps) ? t.steps : [];
  }, [detail]);

  return (
    <div style={{ padding: 16 }}>
      <div style={{ marginBottom: 12 }}>
        <Title level={4} style={{ margin: 0 }}>
          <HistoryOutlined /> Workflow 运行历史
        </Title>
        <Text type="secondary">
          每次 /run 与 /{`{`}id{`}`}/run 都会落审计。历史只读、按组织隔离，
          用于回溯执行细节和排查失败原因。
        </Text>
      </div>

      <Row gutter={12}>
        {/* ============ 左：列表 ============ */}
        <Col span={10}>
          <Card
            size="small"
            title={
              <Space>
                <span>最近运行</span>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  ({rows.length})
                </Text>
              </Space>
            }
            extra={
              <Space size={4}>
                <Input
                  size="small"
                  prefix={<FilterOutlined />}
                  placeholder="按 workflow_id 过滤"
                  value={workflowFilter}
                  onChange={(e) => setWorkflowFilter(e.target.value)}
                  onPressEnter={() => reload()}
                  style={{ width: 220 }}
                  allowClear
                />
                <Button
                  size="small"
                  icon={<ReloadOutlined />}
                  loading={loading}
                  onClick={reload}
                />
              </Space>
            }
            styles={{ body: { padding: 0, maxHeight: '75vh', overflow: 'auto' } }}
          >
            {rows.length === 0 && !loading ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="暂无运行历史"
                style={{ padding: 24 }}
              />
            ) : (
              <List
                size="small"
                dataSource={rows}
                renderItem={(row) => (
                  <List.Item
                    onClick={() => void openRun(row.id)}
                    style={{
                      cursor: 'pointer',
                      padding: '8px 12px',
                      background: row.id === selectedId ? '#e6f4ff' : undefined,
                    }}
                  >
                    <div style={{ width: '100%' }}>
                      <Space size={6} style={{ marginBottom: 2 }}>
                        {statusTag(row.status)}
                        <Text strong style={{ fontSize: 13 }}>
                          {row.workflow_name}
                        </Text>
                        <Text type="secondary" style={{ fontSize: 11 }}>
                          {row.duration_ms}ms
                        </Text>
                      </Space>
                      <div>
                        <Text type="secondary" style={{ fontSize: 11 }}>
                          {fmtTime(row.started_at)}
                          {row.workflow_id === null && (
                            <>
                              {' · '}
                              <Tag color="orange" style={{ marginLeft: 4 }}>
                                inline
                              </Tag>
                            </>
                          )}
                        </Text>
                      </div>
                      {row.error && (
                        <Text
                          type="danger"
                          style={{
                            fontSize: 11,
                            display: 'block',
                            marginTop: 2,
                          }}
                          ellipsis={{ tooltip: row.error }}
                        >
                          {row.error}
                        </Text>
                      )}
                    </div>
                  </List.Item>
                )}
              />
            )}
          </Card>
        </Col>

        {/* ============ 右：详情 ============ */}
        <Col span={14}>
          <Card
            size="small"
            title={
              detail ? (
                <Space>
                  {statusTag(detail.status)}
                  <Text strong>{detail.workflow_name}</Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {fmtTime(detail.started_at)} · {detail.duration_ms}ms
                  </Text>
                </Space>
              ) : (
                <span>运行详情</span>
              )
            }
          >
            {!selectedId && (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="从左侧选择一条运行查看详情"
              />
            )}
            {selectedId && detailLoading && (
              <Text type="secondary">正在加载 trace…</Text>
            )}
            {detail && (
              <>
                {detail.error && (
                  <Alert
                    type="error"
                    showIcon
                    style={{ marginBottom: 8 }}
                    message="Run 级错误"
                    description={
                      <pre style={{
                        margin: 0,
                        whiteSpace: 'pre-wrap',
                        fontSize: 12,
                      }}>
                        {detail.error}
                      </pre>
                    }
                  />
                )}
                {traceSteps.length === 0 ? (
                  <Text type="secondary">该运行未记录任何步骤</Text>
                ) : (
                  <List
                    size="small"
                    bordered
                    dataSource={traceSteps}
                    renderItem={(s: any) => (
                      <List.Item>
                        <div style={{ width: '100%' }}>
                          <Space style={{ marginBottom: 4 }}>
                            {statusTag(s.status)}
                            <Text code>{s.id}</Text>
                            <Text
                              type="secondary"
                              style={{ fontSize: 11 }}
                            >
                              {s.tool} · {s.duration_ms}ms
                            </Text>
                          </Space>
                          {s.error && (
                            <pre style={{
                              fontSize: 12,
                              color: '#a8071a',
                              margin: '4px 0',
                              whiteSpace: 'pre-wrap',
                            }}>
                              {s.error}
                            </pre>
                          )}
                          {s.resolved_args &&
                            Object.keys(s.resolved_args).length > 0 && (
                              <details style={{ marginTop: 4 }}>
                                <summary style={{ fontSize: 11, color: '#888' }}>
                                  resolved_args
                                </summary>
                                <pre style={{
                                  fontSize: 11,
                                  background: '#fafafa',
                                  padding: 6,
                                  margin: '4px 0 0',
                                  maxHeight: 120,
                                  overflow: 'auto',
                                }}>
                                  {JSON.stringify(s.resolved_args, null, 2)}
                                </pre>
                              </details>
                            )}
                          {s.result && (
                            <pre style={{
                              fontSize: 11,
                              background: '#fafafa',
                              padding: 6,
                              margin: '4px 0 0',
                              maxHeight: 160,
                              overflow: 'auto',
                              whiteSpace: 'pre-wrap',
                            }}>
                              {JSON.stringify(s.result, null, 2)}
                            </pre>
                          )}
                        </div>
                      </List.Item>
                    )}
                  />
                )}
              </>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );
}
