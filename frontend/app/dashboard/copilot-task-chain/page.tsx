'use client';

/**
 * Copilot Task Chain 面板 · v2.1 E2.4c.
 *
 * 布局:
 *   ┌────────────────┬─────────────────────────────────────┐
 *   │ 左: 会话列表    │ 右: 选中 chain 的 plan + steps + 操作 │
 *   │ + LLM 自动规划  │  - Plan 列表 (含 revise/reflect)    │
 *   │ + 手写创建      │  - Step 卡片 (含 output/error)      │
 *   └────────────────┴─────────────────────────────────────┘
 *
 * 与 Workflow 编辑器的区别: chain 是 短生命周期、动态可 revise 的对话产物；
 * 这里的 UI 更贴近 Agent 会话流而非 DAG 编辑。
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert, Badge, Button, Card, Col, Empty, Form, Input, List, Modal,
  Popconfirm, Progress, Row, Space, Steps, Tag, Tooltip, Typography,
  message,
} from 'antd';
import {
  BulbOutlined, DeleteOutlined, EditOutlined, PlayCircleOutlined,
  PlusOutlined, ReloadOutlined, RobotOutlined, StopOutlined,
  StepForwardOutlined, ThunderboltOutlined,
} from '@ant-design/icons';

import {
  advanceStep, Approval, autoCreateChain, cancelChain, Chain, createChain,
  decideApproval, getChain, listChainApprovals, listChains, planChain,
  progressPercent, reflectChain, runChain, statusColor, statusLabel, Step,
  Subtask,
} from '@/lib/copilot_task_chain';

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

const EMPTY_PLAN_YAML = `[
  {"title": "列出无人机", "tool": "list_drones", "args": {}, "why": "先看当前机队"}
]`;

function PlanBadge({ chain }: { chain: Chain }) {
  const pct = progressPercent(chain);
  return (
    <Space size={4}>
      <Tag color={statusColor(chain.status) as any}>
        {statusLabel(chain.status)}
      </Tag>
      <Text type="secondary" style={{ fontSize: 12 }}>
        {chain.current_index}/{(chain.plan_json ?? []).length}
      </Text>
    </Space>
  );
}

export default function CopilotTaskChainPage() {
  const [rows, setRows] = useState<Chain[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<
    { chain: Chain; steps: Step[]; revisions: any[] } | null
  >(null);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<
    'advance' | 'run' | 'reflect' | 'cancel' | 'decide' | null
  >(null);

  // Approval decision modal
  const [decideOpen, setDecideOpen] = useState(false);
  const [decideTarget, setDecideTarget] = useState<Approval | null>(null);
  const [decideAction, setDecideAction] = useState<'approved' | 'rejected'>('approved');
  const [decideReason, setDecideReason] = useState('');
  const [decideModsRaw, setDecideModsRaw] = useState('');

  // Create modals
  const [autoOpen, setAutoOpen] = useState(false);
  const [autoGoal, setAutoGoal] = useState('');
  const [autoBusy, setAutoBusy] = useState(false);
  const [autoPreview, setAutoPreview] = useState<Subtask[] | null>(null);

  const [manualOpen, setManualOpen] = useState(false);
  const [manualGoal, setManualGoal] = useState('');
  const [manualPlan, setManualPlan] = useState<string>(EMPTY_PLAN_YAML);
  const [manualBusy, setManualBusy] = useState(false);

  const reloadList = useCallback(async () => {
    setLoading(true);
    try {
      const { items } = await listChains({ limit: 50 });
      setRows(items);
    } catch (e: any) {
      message.error(`列表加载失败: ${e?.message ?? e}`);
    } finally {
      setLoading(false);
    }
  }, []);

  const reloadDetail = useCallback(async (id: string) => {
    try {
      const d = await getChain(id);
      setDetail(d);
      const ap = await listChainApprovals(id);
      setApprovals(ap.items);
    } catch (e: any) {
      message.error(`加载详情失败: ${e?.message ?? e}`);
    }
  }, []);

  useEffect(() => {
    void reloadList();
  }, [reloadList]);

  useEffect(() => {
    if (selectedId) void reloadDetail(selectedId);
    else setDetail(null);
  }, [selectedId, reloadDetail]);

  // ------------------------------------------------------------------
  // Create
  // ------------------------------------------------------------------
  const previewPlan = async () => {
    if (!autoGoal.trim()) {
      message.warning('请填写目标');
      return;
    }
    setAutoBusy(true);
    try {
      const r = await planChain({ goal: autoGoal.trim() });
      setAutoPreview(r.plan);
    } catch (e: any) {
      message.error(`规划失败: ${e?.message ?? e}`);
    } finally {
      setAutoBusy(false);
    }
  };

  const confirmAutoCreate = async () => {
    if (!autoGoal.trim()) return;
    setAutoBusy(true);
    try {
      const c = await autoCreateChain({ goal: autoGoal.trim() });
      message.success('已创建 (LLM 规划)');
      setAutoOpen(false);
      setAutoGoal('');
      setAutoPreview(null);
      await reloadList();
      setSelectedId(c.id);
    } catch (e: any) {
      message.error(`创建失败: ${e?.message ?? e}`);
    } finally {
      setAutoBusy(false);
    }
  };

  const submitManualCreate = async () => {
    if (!manualGoal.trim()) {
      message.warning('请填写目标');
      return;
    }
    let plan: Subtask[];
    try {
      plan = JSON.parse(manualPlan);
      if (!Array.isArray(plan) || plan.length === 0) {
        throw new Error('plan 必须是非空数组');
      }
    } catch (e: any) {
      message.error(`plan JSON 解析失败: ${e?.message ?? e}`);
      return;
    }
    setManualBusy(true);
    try {
      const c = await createChain({ goal: manualGoal.trim(), plan });
      message.success('已创建');
      setManualOpen(false);
      setManualGoal('');
      setManualPlan(EMPTY_PLAN_YAML);
      await reloadList();
      setSelectedId(c.id);
    } catch (e: any) {
      message.error(`创建失败: ${e?.message ?? e}`);
    } finally {
      setManualBusy(false);
    }
  };

  // ------------------------------------------------------------------
  // Execute
  // ------------------------------------------------------------------
  const doAdvance = async () => {
    if (!selectedId) return;
    setBusy('advance');
    try {
      await advanceStep(selectedId);
      await Promise.all([reloadList(), reloadDetail(selectedId)]);
    } catch (e: any) {
      message.error(`执行失败: ${e?.message ?? e}`);
    } finally {
      setBusy(null);
    }
  };

  const doRun = async () => {
    if (!selectedId) return;
    setBusy('run');
    try {
      await runChain(selectedId, 32);
      await Promise.all([reloadList(), reloadDetail(selectedId)]);
    } catch (e: any) {
      message.error(`执行失败: ${e?.message ?? e}`);
    } finally {
      setBusy(null);
    }
  };

  const doReflect = async (apply: boolean) => {
    if (!selectedId) return;
    setBusy('reflect');
    try {
      const r = await reflectChain(selectedId, {
        trigger: 'user_reflect', apply,
      });
      Modal.info({
        title: `LLM 建议 · ${r.suggestion.kind}${apply ? ' (已应用)' : ''}`,
        content: (
          <div>
            <Paragraph strong>原因</Paragraph>
            <Paragraph>{r.suggestion.reason}</Paragraph>
            {r.suggestion.new_tail && (
              <>
                <Paragraph strong>新增/替换步骤</Paragraph>
                <pre style={{ background: '#f5f5f5', padding: 8, fontSize: 12 }}>
                  {JSON.stringify(r.suggestion.new_tail, null, 2)}
                </pre>
              </>
            )}
          </div>
        ),
        width: 600,
      });
      if (apply) {
        await Promise.all([reloadList(), reloadDetail(selectedId)]);
      }
    } catch (e: any) {
      message.error(`反思失败: ${e?.message ?? e}`);
    } finally {
      setBusy(null);
    }
  };

  const doCancel = async () => {
    if (!selectedId) return;
    setBusy('cancel');
    try {
      await cancelChain(selectedId);
      await Promise.all([reloadList(), reloadDetail(selectedId)]);
    } catch (e: any) {
      message.error(`取消失败: ${e?.message ?? e}`);
    } finally {
      setBusy(null);
    }
  };

  const chain = detail?.chain ?? null;
  const canExecute = chain && (chain.status === 'draft' || chain.status === 'running');
  const canReflect = chain && chain.status !== 'completed' && chain.status !== 'cancelled';
  const pendingApprovals = approvals.filter((a) => a.status === 'pending');

  // ------------------------------------------------------------------
  // Approval decisions
  // ------------------------------------------------------------------
  const openDecide = (a: Approval, action: 'approved' | 'rejected') => {
    setDecideTarget(a);
    setDecideAction(action);
    setDecideReason('');
    setDecideModsRaw(a.args_snapshot ? JSON.stringify(a.args_snapshot, null, 2) : '');
    setDecideOpen(true);
  };

  const submitDecide = async () => {
    if (!decideTarget) return;
    if (!decideReason.trim()) {
      message.warning('请填写决策理由');
      return;
    }
    let mods: Record<string, unknown> | undefined;
    if (decideAction === 'approved' && decideModsRaw.trim()) {
      try {
        mods = JSON.parse(decideModsRaw);
      } catch (e: any) {
        message.error(`args 修改 JSON 解析失败: ${e?.message ?? e}`);
        return;
      }
    }
    setBusy('decide');
    try {
      const r = await decideApproval(
        decideTarget.id,
        {
          decision: decideAction,
          reason: decideReason.trim(),
          modifications: mods,
        },
        true,
      );
      message.success(
        decideAction === 'approved'
          ? (r.resumed_step
              ? `已批准并重跑，step 状态: ${r.resumed_step.status}`
              : '已批准（未 resume）')
          : '已拒绝',
      );
      setDecideOpen(false);
      if (selectedId) {
        await Promise.all([reloadList(), reloadDetail(selectedId)]);
      }
    } catch (e: any) {
      message.error(`决策失败: ${e?.message ?? e}`);
    } finally {
      setBusy(null);
    }
  };

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------
  return (
    <div style={{ padding: 24 }}>
      <Title level={3}>
        <RobotOutlined /> Copilot Task Chain
        <Text type="secondary" style={{ fontSize: 14, marginLeft: 12 }}>
          Plan · Execute · Reflect
        </Text>
      </Title>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message='Task Chain 是一次带显式计划的 Agent 会话，与 Workflow 编辑器（静态 DAG）互补：适合"到底该干什么"未知、需要 LLM 边跑边想的场景。'
      />

      <Row gutter={16}>
        {/* ============= 左: 列表 ============= */}
        <Col span={8}>
          <Card
            size="small"
            title={<>会话列表 <Text type="secondary">({rows.length})</Text></>}
            extra={
              <Space size={4}>
                <Tooltip title="LLM 自动规划">
                  <Button
                    type="primary"
                    icon={<ThunderboltOutlined />}
                    size="small"
                    onClick={() => setAutoOpen(true)}
                  >
                    自动
                  </Button>
                </Tooltip>
                <Tooltip title="手写 plan">
                  <Button
                    icon={<PlusOutlined />}
                    size="small"
                    onClick={() => setManualOpen(true)}
                  >
                    手动
                  </Button>
                </Tooltip>
                <Button icon={<ReloadOutlined />} size="small" onClick={reloadList} />
              </Space>
            }
          >
            <List
              loading={loading}
              locale={{ emptyText: <Empty description="暂无会话" /> }}
              dataSource={rows}
              renderItem={(row) => (
                <List.Item
                  onClick={() => setSelectedId(row.id)}
                  style={{
                    cursor: 'pointer',
                    background: row.id === selectedId ? '#e6f4ff' : undefined,
                    padding: '8px 12px',
                  }}
                >
                  <List.Item.Meta
                    title={
                      <Space size={6}>
                        <Text ellipsis style={{ maxWidth: 200 }}>
                          {row.goal}
                        </Text>
                      </Space>
                    }
                    description={
                      <Space size={6}>
                        <PlanBadge chain={row} />
                        <Text type="secondary" style={{ fontSize: 11 }}>
                          {row.updated_at ? new Date(row.updated_at).toLocaleString() : ''}
                        </Text>
                      </Space>
                    }
                  />
                </List.Item>
              )}
            />
          </Card>
        </Col>

        {/* ============= 右: 详情 ============= */}
        <Col span={16}>
          {!chain ? (
            <Card>
              <Empty description="从左侧选择一个 chain 查看详情" />
            </Card>
          ) : (
            <Card
              size="small"
              title={
                <Space>
                  <Text strong>{chain.goal}</Text>
                  <PlanBadge chain={chain} />
                </Space>
              }
              extra={
                <Space size={4}>
                  <Button
                    icon={<StepForwardOutlined />}
                    size="small"
                    disabled={!canExecute}
                    loading={busy === 'advance'}
                    onClick={doAdvance}
                  >
                    单步
                  </Button>
                  <Button
                    type="primary"
                    icon={<PlayCircleOutlined />}
                    size="small"
                    disabled={!canExecute}
                    loading={busy === 'run'}
                    onClick={doRun}
                  >
                    一直跑
                  </Button>
                  <Tooltip title="让 LLM 检查当前进度并给出调整建议">
                    <Button
                      icon={<BulbOutlined />}
                      size="small"
                      disabled={!canReflect}
                      loading={busy === 'reflect'}
                      onClick={() => doReflect(false)}
                    >
                      反思
                    </Button>
                  </Tooltip>
                  <Tooltip title="让 LLM 直接应用建议">
                    <Button
                      icon={<EditOutlined />}
                      size="small"
                      disabled={!canReflect}
                      onClick={() => doReflect(true)}
                    >
                      反思&应用
                    </Button>
                  </Tooltip>
                  <Popconfirm
                    title="取消该 chain？"
                    onConfirm={doCancel}
                    disabled={!canExecute}
                  >
                    <Button
                      danger icon={<StopOutlined />} size="small"
                      disabled={!canExecute}
                      loading={busy === 'cancel'}
                    >
                      取消
                    </Button>
                  </Popconfirm>
                </Space>
              }
            >
              <Progress
                percent={progressPercent(chain)}
                status={
                  chain.status === 'failed' ? 'exception' :
                  chain.status === 'completed' ? 'success' :
                  chain.status === 'running' ? 'active' : 'normal'
                }
                size="small"
                style={{ marginBottom: 12 }}
              />

              {chain.error && (
                <Alert
                  type="error" showIcon
                  message={chain.error}
                  style={{ marginBottom: 12 }}
                />
              )}

              {/* Pending approvals banner */}
              {pendingApprovals.length > 0 && (
                <Alert
                  type="warning" showIcon
                  style={{ marginBottom: 12 }}
                  message={`${pendingApprovals.length} 个步骤等待审批`}
                  description={
                    <div style={{ marginTop: 4 }}>
                      {pendingApprovals.map((a) => (
                        <div
                          key={a.id}
                          style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 4 }}
                        >
                          <Tag color="red">{a.risk_level}</Tag>
                          <Tag>{a.permission}</Tag>
                          <Text code>{a.tool_name}</Text>
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            #{a.step_index + 1} · {a.required_reason}
                          </Text>
                          <span style={{ flex: 1 }} />
                          <Button
                            size="small" type="primary"
                            onClick={() => openDecide(a, 'approved')}
                          >
                            批准
                          </Button>
                          <Button
                            size="small" danger
                            onClick={() => openDecide(a, 'rejected')}
                          >
                            拒绝
                          </Button>
                        </div>
                      ))}
                    </div>
                  }
                />
              )}

              {/* Plan */}
              <Card size="small" type="inner" title="Plan (subtasks)" style={{ marginBottom: 12 }}>
                <Steps
                  direction="vertical" size="small"
                  current={chain.current_index}
                  items={(chain.plan_json ?? []).map((st, i) => {
                    const step = detail?.steps.find((x) => x.step_index === i);
                    return {
                      title: <Text strong>{st.title}</Text>,
                      description: (
                        <div>
                          <Text code>{st.tool}</Text>
                          {st.why && <Paragraph type="secondary" style={{ margin: 0, fontSize: 12 }}>{st.why}</Paragraph>}
                          {step && (
                            <Space size={4} style={{ marginTop: 4 }}>
                              <Tag color={statusColor(step.status) as any}>
                                {statusLabel(step.status)}
                              </Tag>
                              {step.error && (
                                <Text type="danger" style={{ fontSize: 12 }}>{step.error}</Text>
                              )}
                            </Space>
                          )}
                        </div>
                      ),
                      status: step
                        ? step.status === 'succeeded' ? 'finish'
                          : step.status === 'failed' ? 'error'
                          : 'process'
                        : (i < chain.current_index ? 'finish' : 'wait'),
                    };
                  })}
                />
              </Card>

              {/* Steps outputs */}
              {(detail?.steps.length ?? 0) > 0 && (
                <Card size="small" type="inner" title="Step outputs">
                  {detail!.steps.map((s) => (
                    <div key={s.id} style={{ marginBottom: 8 }}>
                      <Space size={6}>
                        <Badge status={
                          s.status === 'succeeded' ? 'success'
                          : s.status === 'failed' ? 'error' : 'processing'
                        } />
                        <Text strong>#{s.step_index + 1} · {s.title}</Text>
                        <Text code>{s.tool}</Text>
                      </Space>
                      {s.output_json !== null && s.output_json !== undefined && (
                        <pre style={{
                          background: '#f5f5f5', padding: 8, fontSize: 11,
                          margin: '4px 0 0 24px', maxHeight: 200, overflow: 'auto',
                        }}>
                          {JSON.stringify(s.output_json, null, 2)}
                        </pre>
                      )}
                    </div>
                  ))}
                </Card>
              )}

              {/* Revisions */}
              {(detail?.revisions.length ?? 0) > 0 && (
                <Card size="small" type="inner" title={`Revisions (${detail!.revisions.length})`} style={{ marginTop: 12 }}>
                  {detail!.revisions.map((r) => (
                    <div key={r.id} style={{ marginBottom: 6, fontSize: 12 }}>
                      <Space size={6}>
                        <Tag>{r.kind}</Tag>
                        <Text type="secondary">@step {r.at_step_index}</Text>
                        <Text>{r.reason}</Text>
                      </Space>
                    </div>
                  ))}
                </Card>
              )}
            </Card>
          )}
        </Col>
      </Row>

      {/* ============= 创建 (LLM auto) modal ============= */}
      <Modal
        open={autoOpen}
        title={<><ThunderboltOutlined /> LLM 自动规划</>}
        onCancel={() => {
          setAutoOpen(false);
          setAutoPreview(null);
        }}
        onOk={confirmAutoCreate}
        okText="创建 chain"
        confirmLoading={autoBusy}
        okButtonProps={{ disabled: !autoGoal.trim() }}
        width={640}
      >
        <Form layout="vertical">
          <Form.Item label="目标 (goal)" required>
            <TextArea
              rows={3} value={autoGoal}
              placeholder="例: 查看甘孜州所有巡检无人机的电量状态，把低于30%的列出来"
              onChange={(e) => setAutoGoal(e.target.value)}
            />
          </Form.Item>
          <Space style={{ marginBottom: 12 }}>
            <Button
              icon={<BulbOutlined />} onClick={previewPlan}
              loading={autoBusy} disabled={!autoGoal.trim()}
            >
              先预览计划
            </Button>
            <Text type="secondary" style={{ fontSize: 12 }}>
              预览不落库；点"创建 chain"才会保存
            </Text>
          </Space>
          {autoPreview && (
            <Card size="small" type="inner" title="LLM 生成的计划">
              <List
                dataSource={autoPreview}
                renderItem={(st, i) => (
                  <List.Item>
                    <List.Item.Meta
                      title={<Space><Text>{i + 1}.</Text><Text strong>{st.title}</Text><Text code>{st.tool}</Text></Space>}
                      description={<Text type="secondary">{st.why}</Text>}
                    />
                  </List.Item>
                )}
              />
            </Card>
          )}
        </Form>
      </Modal>

      {/* ============= 创建 (manual) modal ============= */}
      <Modal
        open={manualOpen}
        title={<><PlusOutlined /> 手动创建 chain</>}
        onCancel={() => setManualOpen(false)}
        onOk={submitManualCreate}
        confirmLoading={manualBusy}
        width={720}
      >
        <Form layout="vertical">
          <Form.Item label="目标 (goal)" required>
            <TextArea
              rows={2} value={manualGoal}
              onChange={(e) => setManualGoal(e.target.value)}
            />
          </Form.Item>
          <Form.Item label="Plan (JSON array of subtasks)" required>
            <TextArea
              rows={12} value={manualPlan}
              onChange={(e) => setManualPlan(e.target.value)}
              style={{ fontFamily: 'monospace', fontSize: 12 }}
            />
          </Form.Item>
        </Form>
      </Modal>
      {/* ============= 审批决策 modal ============= */}
      <Modal
        open={decideOpen}
        title={
          decideAction === 'approved'
            ? <><PlayCircleOutlined /> 批准并 resume</>
            : <><StopOutlined /> 拒绝</>
        }
        okText={decideAction === 'approved' ? '批准' : '拒绝'}
        okButtonProps={{
          danger: decideAction === 'rejected',
          disabled: !decideReason.trim(),
        }}
        onCancel={() => setDecideOpen(false)}
        onOk={submitDecide}
        confirmLoading={busy === 'decide'}
        width={640}
      >
        {decideTarget && (
          <div style={{ marginBottom: 12 }}>
            <Space>
              <Tag color="red">{decideTarget.risk_level}</Tag>
              <Tag>{decideTarget.permission}</Tag>
              <Text code>{decideTarget.tool_name}</Text>
              <Text type="secondary">#{decideTarget.step_index + 1}</Text>
            </Space>
            <Paragraph type="secondary" style={{ margin: '6px 0' }}>
              {decideTarget.required_reason}
            </Paragraph>
          </div>
        )}
        <Form layout="vertical">
          <Form.Item label="决策理由" required>
            <TextArea
              rows={3} value={decideReason}
              placeholder="记录本次审批的判断依据，会入库审计"
              onChange={(e) => setDecideReason(e.target.value)}
            />
          </Form.Item>
          {decideAction === 'approved' && (
            <Form.Item
              label="args 修改（可选 · JSON）"
              tooltip="批准前可以调整参数，例如降低任务半径。留空则用原参数重跑。"
            >
              <TextArea
                rows={8} value={decideModsRaw}
                style={{ fontFamily: 'monospace', fontSize: 12 }}
                onChange={(e) => setDecideModsRaw(e.target.value)}
              />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </div>
  );
}
