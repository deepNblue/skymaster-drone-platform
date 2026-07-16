/**
 * T12.3 · Copilot workflow schedule manager UI.
 *
 * Dedicated sub-page (linked from the editor). Lists all schedules
 * belonging to the current org, lets the user create/enable/disable/
 * delete them. Includes a lightweight cron helper (dropdown of
 * common patterns) — no live "next 5 fire times" preview yet, that's
 * a T12.4 nice-to-have.
 */
'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import {
  Alert,
  Button,
  Card,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  ArrowLeftOutlined,
  ClockCircleOutlined,
  DeleteOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons';

import {
  createSchedule,
  deleteSchedule,
  listSchedules,
  listWorkflows,
  updateSchedule,
  WorkflowRecord,
  WorkflowSchedule,
} from '@/lib/copilot_workflows';

const { Title, Text, Paragraph } = Typography;

/** Common cron patterns for the dropdown helper. */
const CRON_PRESETS: Array<{ label: string; value: string }> = [
  { label: '每天 09:00 (0 9 * * *)', value: '0 9 * * *' },
  { label: '每小时整点 (0 * * * *)', value: '0 * * * *' },
  { label: '每 15 分钟 (*/15 * * * *)', value: '*/15 * * * *' },
  { label: '每周一 09:00 (0 9 * * MON)', value: '0 9 * * MON' },
  { label: '每月 1 号 00:00 (0 0 1 * *)', value: '0 0 1 * *' },
  { label: '工作日 08:30 (30 8 * * MON-FRI)', value: '30 8 * * MON-FRI' },
];

function fmtTime(iso: string | null): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false });
  } catch {
    return iso;
  }
}

function StatusTag({ s }: { s: WorkflowSchedule }) {
  if (!s.enabled) {
    return <Tag>已停用</Tag>;
  }
  if (s.last_fire_status === 'failed') {
    return <Tag color="red">上次失败</Tag>;
  }
  if (s.last_fire_status === 'ok') {
    return <Tag color="green">运行中</Tag>;
  }
  return <Tag color="blue">已启用 · 待触发</Tag>;
}

export default function SchedulesPage() {
  const [rows, setRows] = useState<WorkflowSchedule[]>([]);
  const [workflows, setWorkflows] = useState<WorkflowRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form] = Form.useForm<{
    workflow_id: string;
    cron_expr: string;
    inputs_json: string;
    enabled: boolean;
  }>();

  const wfNameById = useMemo(() => {
    const m = new Map<string, string>();
    for (const wf of workflows) m.set(wf.id, wf.name);
    return m;
  }, [workflows]);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [sc, wf] = await Promise.all([
        listSchedules(),
        listWorkflows(),
      ]);
      setRows(sc);
      setWorkflows(wf);
    } catch (e: any) {
      message.error(`加载失败: ${e?.message ?? e}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const openCreate = useCallback(() => {
    form.resetFields();
    form.setFieldsValue({
      cron_expr: '0 9 * * *',
      enabled: true,
      inputs_json: '{}',
    });
    setModalOpen(true);
  }, [form]);

  const submitCreate = useCallback(async () => {
    let vals: any;
    try {
      vals = await form.validateFields();
    } catch {
      return;
    }
    let inputs: Record<string, unknown> = {};
    if (vals.inputs_json?.trim()) {
      try {
        inputs = JSON.parse(vals.inputs_json);
      } catch (e: any) {
        message.error(`inputs JSON 解析失败: ${e?.message ?? e}`);
        return;
      }
    }
    setCreating(true);
    try {
      await createSchedule({
        workflow_id: vals.workflow_id,
        cron_expr: vals.cron_expr,
        inputs,
        enabled: vals.enabled ?? true,
      });
      message.success('已创建');
      setModalOpen(false);
      await reload();
    } catch (e: any) {
      message.error(`创建失败: ${e?.message ?? e}`);
    } finally {
      setCreating(false);
    }
  }, [form, reload]);

  const toggleEnabled = useCallback(
    async (row: WorkflowSchedule, enabled: boolean) => {
      try {
        await updateSchedule(row.id, { enabled });
        message.success(enabled ? '已启用' : '已停用');
        await reload();
      } catch (e: any) {
        message.error(`更新失败: ${e?.message ?? e}`);
      }
    },
    [reload],
  );

  const doDelete = useCallback(
    async (id: string) => {
      try {
        await deleteSchedule(id);
        message.success('已删除');
        await reload();
      } catch (e: any) {
        message.error(`删除失败: ${e?.message ?? e}`);
      }
    },
    [reload],
  );

  const columns = [
    {
      title: 'Workflow',
      dataIndex: 'workflow_id',
      key: 'workflow_id',
      render: (id: string) => wfNameById.get(id) ?? id.slice(0, 8),
    },
    {
      title: 'Cron',
      dataIndex: 'cron_expr',
      key: 'cron_expr',
      render: (v: string) => <code>{v}</code>,
    },
    {
      title: '状态',
      key: 'status',
      render: (_: unknown, row: WorkflowSchedule) => <StatusTag s={row} />,
    },
    {
      title: '下次触发',
      dataIndex: 'next_fire_at',
      key: 'next_fire_at',
      render: fmtTime,
    },
    {
      title: '上次触发',
      dataIndex: 'last_fire_at',
      key: 'last_fire_at',
      render: fmtTime,
    },
    {
      title: '操作',
      key: 'ops',
      render: (_: unknown, row: WorkflowSchedule) => (
        <Space size={4}>
          <Switch
            size="small"
            checked={row.enabled}
            onChange={(v) => void toggleEnabled(row, v)}
          />
          <Popconfirm
            title="删除该定时任务？"
            onConfirm={() => void doDelete(row.id)}
          >
            <Button size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 16 }}>
      <div style={{ marginBottom: 12 }}>
        <Space>
          <Link href="/dashboard/copilot-workflows">
            <Button size="small" icon={<ArrowLeftOutlined />}>
              返回编辑器
            </Button>
          </Link>
          <Title level={4} style={{ margin: 0 }}>
            <ClockCircleOutlined /> 定时调度
          </Title>
        </Space>
        <Paragraph type="secondary" style={{ marginTop: 4 }}>
          绑定 workflow 到 cron 表达式；启用后由 scheduler daemon 自动
          触发，运行历史落入常规 Workflow Runs 表（<code>trace.scheduled=true</code>）。
        </Paragraph>
      </div>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="调度守护进程需要在服务端启用 START_COPILOT_SCHEDULER=1 才会真正触发。开发环境默认关闭。"
      />

      <Card
        size="small"
        title={
          <Space>
            <Text strong>Schedules ({rows.length})</Text>
          </Space>
        }
        extra={
          <Space>
            <Button
              size="small"
              icon={<ReloadOutlined />}
              onClick={() => void reload()}
            >
              刷新
            </Button>
            <Button
              type="primary"
              size="small"
              icon={<PlusOutlined />}
              onClick={openCreate}
            >
              新建
            </Button>
          </Space>
        }
      >
        {rows.length === 0 && !loading ? (
          <Empty description="尚未配置任何定时任务" />
        ) : (
          <Table
            size="small"
            rowKey="id"
            loading={loading}
            dataSource={rows}
            columns={columns as any}
            pagination={false}
          />
        )}
      </Card>

      <Modal
        title="新建定时任务"
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => void submitCreate()}
        confirmLoading={creating}
        okText="创建"
        cancelText="取消"
        width={560}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="workflow_id"
            label="Workflow"
            rules={[{ required: true, message: '请选择 workflow' }]}
          >
            <Select
              placeholder="选择要定时运行的 workflow"
              options={workflows.map((wf) => ({
                label: wf.name,
                value: wf.id,
              }))}
              showSearch
              optionFilterProp="label"
            />
          </Form.Item>

          <Form.Item
            name="cron_expr"
            label="Cron 表达式 (5-field, UTC)"
            rules={[
              { required: true, message: '请输入 cron 表达式' },
              { max: 64 },
            ]}
            help="服务端使用 UTC 时区。示例：'0 9 * * *' = 每天 UTC 09:00"
          >
            <Input placeholder="0 9 * * *" />
          </Form.Item>

          <Form.Item label="常用模板">
            <Select
              placeholder="选中后自动填入上方 cron 输入框"
              onChange={(v) => form.setFieldsValue({ cron_expr: v })}
              options={CRON_PRESETS.map((p) => ({
                label: p.label,
                value: p.value,
              }))}
              allowClear
            />
          </Form.Item>

          <Form.Item
            name="inputs_json"
            label="Inputs (JSON, 可选)"
            help="将作为 workflow 的固定 inputs 快照，例如 {&quot;drone_id&quot;: &quot;...&quot;}"
          >
            <Input.TextArea rows={3} placeholder="{}" />
          </Form.Item>

          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch defaultChecked />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
