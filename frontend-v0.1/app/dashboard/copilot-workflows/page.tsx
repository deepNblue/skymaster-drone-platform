'use client';

/**
 * Copilot Workflow Editor · T10.7 (v2.1 E2.1).
 *
 * A stripped-down workbench that gives non-CLI users access to the
 * full workflow lifecycle backed by lib/copilot_workflows.ts:
 *
 *   ┌───────────────┬────────────────────────────────┐
 *   │ 左: workflow  │  右上: YAML 编辑器             │
 *   │ 列表          │  右中: Save/Run 工具条         │
 *   │ + 新建按钮    │  右下: 校验 / 运行结果 tab      │
 *   └───────────────┴────────────────────────────────┘
 *
 * Deliberately avoids Monaco — that would drag in a ~5MB dep tree.
 * A plain <Input.TextArea> with monospaced font is 90% of the value
 * for authoring YAML at this stage; power users can copy into their
 * own IDE.
 *
 * Design decisions:
 *   * List-driven navigation → click a row to load it into the editor.
 *     No dirty-flag save prompts yet (v0.1 keeps it simple).
 *   * The "验证" button calls /validate; a failure returns 200 with
 *     ok=false, so the button never surfaces a scary red error — it
 *     just shows the diagnostic inline.
 *   * "运行" needs auth in the JWT + inputs from a JSON textbox; we
 *     parse it locally before hitting the network so obvious typos
 *     don't waste a round-trip.
 *   * Update flow uses the row's version — the backend rejects stale
 *     writes with 409, which we surface via message.error(). No auto
 *     retry (that would silently overwrite someone else's edits).
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Input,
  List,
  Modal,
  Popconfirm,
  Row,
  Space,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  DeleteOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
  SaveOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CodeOutlined,
  BookOutlined,
} from '@ant-design/icons';

import {
  createWorkflow,
  deleteWorkflow,
  getPlaybook,
  listPlaybooks,
  listWorkflows,
  Playbook,
  runInlineWorkflow,
  runStoredWorkflow,
  updateWorkflow,
  validateWorkflow,
  WorkflowRecord,
  WorkflowRun,
  WorkflowValidation,
} from '@/lib/copilot_workflows';

const { Title, Text, Paragraph } = Typography;

const SAMPLE_DSL = `version: "0.1"
name: "example-mission-briefing"
description: "查询所有无人机和最近的检测事件"
steps:
  - id: list
    tool: list_drones
    args: {}
  - id: detections
    tool: list_detections
    args:
      limit: 20
`;

// =========================================================================
// A small helper: given a run trace, produce a status tag palette.
// =========================================================================
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


export default function CopilotWorkflowsPage() {
  // -- server state --
  const [rows, setRows] = useState<WorkflowRecord[]>([]);
  const [loading, setLoading] = useState(false);

  // -- editor state --
  // selectedId=null → we're editing a *new* draft not yet saved
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [currentVersion, setCurrentVersion] = useState<number>(0);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [yamlText, setYamlText] = useState<string>(SAMPLE_DSL);
  const [inputsJson, setInputsJson] = useState<string>('{}');

  // -- validation / run outcomes --
  const [validation, setValidation] = useState<WorkflowValidation | null>(null);
  const [run, setRun] = useState<WorkflowRun | null>(null);
  const [busy, setBusy] = useState<'save' | 'validate' | 'run' | null>(null);

  // -- Playbook picker modal (T11.1) --
  const [pbOpen, setPbOpen] = useState(false);
  const [pbList, setPbList] = useState<Playbook[]>([]);
  const [pbLoading, setPbLoading] = useState(false);
  // T11.4: filter state, sticky within the modal session.
  const [pbTag, setPbTag] = useState<string>('');
  const [pbSearch, setPbSearch] = useState<string>('');

  const isNew = selectedId === null;

  // Fetch list on mount + provide a manual reload button.
  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const list = await listWorkflows();
      setRows(list);
    } catch (e: any) {
      message.error(`列表加载失败: ${e?.message ?? e}`);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void reload();
  }, [reload]);

  // -- editor handlers --
  const openRow = (row: WorkflowRecord) => {
    setSelectedId(row.id);
    setCurrentVersion(row.version);
    setName(row.name);
    setDescription(row.description);
    setYamlText(row.dsl_yaml);
    setValidation(null);
    setRun(null);
  };

  const newDraft = () => {
    setSelectedId(null);
    setCurrentVersion(0);
    setName('untitled');
    setDescription('');
    setYamlText(SAMPLE_DSL);
    setValidation(null);
    setRun(null);
  };

  // ------- Playbook picker (T11.1 / T11.4) -------
  const loadPlaybooks = useCallback(async () => {
    setPbLoading(true);
    try {
      const items = await listPlaybooks({
        tag: pbTag || undefined,
        q: pbSearch.trim() || undefined,
      });
      setPbList(items);
    } catch (e: any) {
      message.error(`Playbook 加载失败: ${e?.message ?? e}`);
    } finally {
      setPbLoading(false);
    }
  }, [pbTag, pbSearch]);

  const openPlaybookPicker = useCallback(async () => {
    setPbOpen(true);
    await loadPlaybooks();
  }, [loadPlaybooks]);

  // Reload whenever filter changes while modal open.
  useEffect(() => {
    if (pbOpen) {
      void loadPlaybooks();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pbTag]);

  /** Fork one playbook into a fresh unsaved draft. User can then edit + Save
   *  to persist under their org — never modifies the seed row. */
  const forkPlaybook = (pb: Playbook) => {
    setSelectedId(null);
    setCurrentVersion(0);
    setName(`我的-${pb.slug}`);
    setDescription(`来自 playbook: ${pb.name}`);
    setYamlText(pb.dsl_yaml);
    setInputsJson(
      Object.keys(pb.sample_inputs).length > 0
        ? JSON.stringify(pb.sample_inputs, null, 2)
        : '{}'
    );
    setValidation(null);
    setRun(null);
    setPbOpen(false);
    message.success(`已加载 playbook: ${pb.name}，请编辑后保存`);
  };

  const parseInputs = useCallback((): Record<string, unknown> | null => {
    const raw = inputsJson.trim();
    if (!raw) return {};
    try {
      const parsed = JSON.parse(raw);
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        message.error('inputs 必须是 JSON 对象');
        return null;
      }
      return parsed as Record<string, unknown>;
    } catch (e: any) {
      message.error(`inputs JSON 解析失败: ${e?.message ?? e}`);
      return null;
    }
  }, [inputsJson]);

  const handleValidate = async () => {
    setBusy('validate');
    setValidation(null);
    try {
      const v = await validateWorkflow(yamlText);
      setValidation(v);
      if (v.ok) {
        message.success(`✓ 语义 OK — ${v.steps.length} 个步骤，涉及 ${v.tools_used.length} 个工具`);
      }
    } catch (e: any) {
      message.error(`验证请求失败: ${e?.message ?? e}`);
    } finally {
      setBusy(null);
    }
  };

  const handleSave = async () => {
    if (!name.trim()) {
      message.warning('请填写工作流名称');
      return;
    }
    setBusy('save');
    try {
      if (isNew) {
        const created = await createWorkflow({
          name: name.trim(),
          description: description.trim(),
          dsl_yaml: yamlText,
        });
        setSelectedId(created.id);
        setCurrentVersion(created.version);
        message.success(`✓ 已创建 (id ${created.id.slice(0, 8)})`);
      } else {
        const updated = await updateWorkflow(selectedId!, {
          version: currentVersion,
          name: name.trim(),
          description: description.trim(),
          dsl_yaml: yamlText,
        });
        setCurrentVersion(updated.version);
        message.success(`✓ 已更新 v${updated.version}`);
      }
      await reload();
    } catch (e: any) {
      const msg = String(e?.message ?? e);
      if (msg.includes('409')) {
        message.error('保存冲突：他人已修改此工作流，请刷新后再保存');
      } else if (msg.includes('400')) {
        message.error(`DSL 校验失败: ${msg}`);
      } else {
        message.error(`保存失败: ${msg}`);
      }
    } finally {
      setBusy(null);
    }
  };

  const handleRun = async () => {
    const inputs = parseInputs();
    if (inputs === null) return;
    setBusy('run');
    setRun(null);
    try {
      // If we've got a saved id use stored-run so ownership + audit is preserved.
      // Otherwise fall back to inline run for drafts.
      const r = isNew
        ? await runInlineWorkflow(yamlText, inputs)
        : await runStoredWorkflow(selectedId!, inputs);
      setRun(r);
      if (r.status === 'ok') {
        message.success(`✓ 运行完成 — ${r.duration_ms}ms`);
      } else {
        message.warning(`运行失败：${r.error ?? '见步骤详情'}`);
      }
    } catch (e: any) {
      message.error(`运行请求失败: ${e?.message ?? e}`);
    } finally {
      setBusy(null);
    }
  };

  const handleDelete = async () => {
    if (!selectedId) return;
    try {
      await deleteWorkflow(selectedId);
      message.success('已删除');
      newDraft();
      await reload();
    } catch (e: any) {
      message.error(`删除失败: ${e?.message ?? e}`);
    }
  };

  const validationBlock = useMemo(() => {
    if (!validation) return null;
    if (validation.ok) {
      return (
        <Alert
          type="success"
          showIcon
          icon={<CheckCircleOutlined />}
          message={<span>校验通过 · {validation.name}</span>}
          description={
            <div style={{ fontSize: 12 }}>
              <div>步骤顺序: {validation.steps.join(' → ') || '(空)'}</div>
              <div>使用的工具: {validation.tools_used.join(', ') || '(无)'}</div>
            </div>
          }
        />
      );
    }
    return (
      <Alert
        type="error"
        showIcon
        message={`校验失败 · ${validation.error_type ?? 'unknown'}`}
        description={
          <pre style={{
            margin: 0,
            whiteSpace: 'pre-wrap',
            fontSize: 12,
            fontFamily: 'ui-monospace, Menlo, monospace',
          }}>
            {validation.error ?? ''}
          </pre>
        }
      />
    );
  }, [validation]);

  const runBlock = useMemo(() => {
    if (!run) return <Empty description="尚未运行" />;
    return (
      <div>
        <Space style={{ marginBottom: 8 }}>
          {statusTag(run.status)}
          <Text type="secondary">{run.duration_ms}ms</Text>
          <Text strong>{run.workflow_name}</Text>
          {run.error && (
            <Text type="danger" style={{ fontSize: 12 }}>
              {run.error}
            </Text>
          )}
        </Space>
        <List
          size="small"
          bordered
          dataSource={run.steps}
          renderItem={(s) => (
            <List.Item>
              <div style={{ width: '100%' }}>
                <Space style={{ marginBottom: 4 }}>
                  {statusTag(s.status)}
                  <Text code>{s.id}</Text>
                  <Text type="secondary" style={{ fontSize: 11 }}>
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
                {s.result && (
                  <pre style={{
                    fontSize: 11,
                    background: '#fafafa',
                    padding: 6,
                    margin: 0,
                    maxHeight: 120,
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
      </div>
    );
  }, [run]);

  return (
    <div style={{ padding: 16 }}>
      <div style={{ marginBottom: 12 }}>
        <Title level={4} style={{ margin: 0 }}>
          <CodeOutlined /> Copilot Workflow 编辑器
        </Title>
        <Space size={12} align="center" style={{ marginTop: 4 }}>
          <Text type="secondary">
            用 YAML 编写、保存、运行工作流。保存后可在 Copilot v2 中命名调用。
          </Text>
          <Link href="/dashboard/copilot-workflows/schedules">
            <Button size="small" icon={<ClockCircleOutlined />}>
              定时调度
            </Button>
          </Link>
        </Space>
      </div>

      <Row gutter={12}>
        {/* ============ 左侧: 列表 ============ */}
        <Col span={6}>
          <Card
            size="small"
            title="我的工作流"
            extra={
              <Space size={4}>
                <Button
                  size="small"
                  icon={<ReloadOutlined />}
                  loading={loading}
                  onClick={reload}
                />
                <Button
                  size="small"
                  icon={<BookOutlined />}
                  onClick={openPlaybookPicker}
                >
                  Playbook
                </Button>
                <Button
                  size="small"
                  type="primary"
                  icon={<PlusOutlined />}
                  onClick={newDraft}
                >
                  新建
                </Button>
              </Space>
            }
            styles={{ body: { padding: 0, maxHeight: '75vh', overflow: 'auto' } }}
          >
            {rows.length === 0 && !loading ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="尚无工作流"
                style={{ padding: 24 }}
              />
            ) : (
              <List
                size="small"
                dataSource={rows}
                renderItem={(row) => (
                  <List.Item
                    onClick={() => openRow(row)}
                    style={{
                      cursor: 'pointer',
                      padding: '8px 12px',
                      background: row.id === selectedId ? '#e6f4ff' : undefined,
                    }}
                  >
                    <div style={{ width: '100%' }}>
                      <Text strong style={{ fontSize: 13 }}>
                        {row.name}
                      </Text>
                      <div>
                        <Text type="secondary" style={{ fontSize: 11 }}>
                          v{row.version} ·{' '}
                          {new Date(row.updated_at).toLocaleString()}
                        </Text>
                      </div>
                    </div>
                  </List.Item>
                )}
              />
            )}
          </Card>
        </Col>

        {/* ============ 右侧: 编辑器 + 工具条 + 结果 ============ */}
        <Col span={18}>
          <Card
            size="small"
            title={
              <Space>
                {isNew ? (
                  <Tag color="blue">新建草稿</Tag>
                ) : (
                  <Tag color="green">v{currentVersion}</Tag>
                )}
                <Input
                  placeholder="工作流名称"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  style={{ width: 240 }}
                />
                <Input
                  placeholder="描述（可选）"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  style={{ width: 320 }}
                />
              </Space>
            }
            extra={
              <Space size={4}>
                <Button
                  icon={<CheckCircleOutlined />}
                  loading={busy === 'validate'}
                  onClick={handleValidate}
                >
                  验证
                </Button>
                <Button
                  type="primary"
                  icon={<SaveOutlined />}
                  loading={busy === 'save'}
                  onClick={handleSave}
                >
                  保存
                </Button>
                <Button
                  type="primary"
                  danger
                  icon={<PlayCircleOutlined />}
                  loading={busy === 'run'}
                  onClick={handleRun}
                >
                  运行
                </Button>
                {!isNew && (
                  <Popconfirm
                    title="确认删除"
                    description="此操作会软删除该工作流。"
                    okText="删除"
                    okType="danger"
                    cancelText="取消"
                    onConfirm={handleDelete}
                  >
                    <Button icon={<DeleteOutlined />} danger />
                  </Popconfirm>
                )}
              </Space>
            }
          >
            <Row gutter={12}>
              <Col span={16}>
                <div style={{ marginBottom: 4 }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    DSL (YAML)
                  </Text>
                </div>
                <Input.TextArea
                  value={yamlText}
                  onChange={(e) => setYamlText(e.target.value)}
                  autoSize={{ minRows: 20, maxRows: 32 }}
                  style={{
                    fontFamily: 'ui-monospace, Menlo, Consolas, monospace',
                    fontSize: 13,
                  }}
                  spellCheck={false}
                />
              </Col>
              <Col span={8}>
                <div style={{ marginBottom: 4 }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    运行时输入 (JSON)
                  </Text>
                </div>
                <Input.TextArea
                  value={inputsJson}
                  onChange={(e) => setInputsJson(e.target.value)}
                  autoSize={{ minRows: 6, maxRows: 12 }}
                  style={{
                    fontFamily: 'ui-monospace, Menlo, Consolas, monospace',
                    fontSize: 12,
                  }}
                  spellCheck={false}
                />
                <div style={{ marginTop: 10 }}>{validationBlock}</div>
              </Col>
            </Row>
          </Card>

          <Card
            size="small"
            title="运行结果"
            style={{ marginTop: 12 }}
          >
            {runBlock}
          </Card>
        </Col>
      </Row>

      {/* ============ Playbook picker modal (T11.1) ============ */}
      <Modal
        title="选择官方 Playbook"
        open={pbOpen}
        onCancel={() => setPbOpen(false)}
        footer={null}
        width={720}
      >
        {/* --- T11.4 filter bar --- */}
        <Space
          direction="horizontal"
          size={8}
          style={{ marginBottom: 12, width: '100%' }}
          wrap
        >
          <Input
            allowClear
            size="small"
            style={{ width: 220 }}
            placeholder="按名称/描述搜索"
            value={pbSearch}
            onChange={(e) => setPbSearch(e.target.value)}
            onPressEnter={() => void loadPlaybooks()}
          />
          <Button
            size="small"
            onClick={() => setPbTag('')}
            type={pbTag === '' ? 'primary' : 'default'}
          >
            全部
          </Button>
          <Button
            size="small"
            onClick={() => setPbTag('ops')}
            type={pbTag === 'ops' ? 'primary' : 'default'}
          >
            运维
          </Button>
          <Button
            size="small"
            onClick={() => setPbTag('domain')}
            type={pbTag === 'domain' ? 'primary' : 'default'}
          >
            行业
          </Button>
          <Button
            size="small"
            onClick={() => setPbTag('readonly')}
            type={pbTag === 'readonly' ? 'primary' : 'default'}
          >
            只读
          </Button>
          <Button
            size="small"
            onClick={() => setPbTag('sensitive')}
            type={pbTag === 'sensitive' ? 'primary' : 'default'}
          >
            含审批
          </Button>
        </Space>

        {pbLoading ? (
          <Text type="secondary">加载中…</Text>
        ) : pbList.length === 0 ? (
          <Empty description="暂无 playbook" />
        ) : (
          <List
            size="small"
            dataSource={pbList}
            renderItem={(pb) => (
              <List.Item
                actions={[
                  <Button
                    key="fork"
                    type="primary"
                    size="small"
                    onClick={() => forkPlaybook(pb)}
                  >
                    加载到编辑器
                  </Button>,
                ]}
              >
                <List.Item.Meta
                  title={<Text strong>{pb.name}</Text>}
                  description={
                    <div>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {pb.description}
                      </Text>
                      <div style={{ marginTop: 4 }}>
                        <Tag>{pb.slug}</Tag>
                        {(pb.tags ?? []).map((t) => (
                          <Tag color="geekblue" key={t}>{t}</Tag>
                        ))}
                        {Object.keys(pb.sample_inputs).length > 0 && (
                          <Tag color="blue">带示例输入</Tag>
                        )}
                      </div>
                    </div>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Modal>
    </div>
  );
}
