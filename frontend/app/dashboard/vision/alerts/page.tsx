/**
 * E3.3 · Detection alert rules dashboard.
 * URL: /dashboard/vision/alerts
 */
'use client';
import {
  Alert, Button, Card, Empty, Form, Input, InputNumber, Modal, Select,
  Space, Switch, Table, Tag, Typography, message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useCallback, useEffect, useState } from 'react';

import {
  AlertFire, AlertRule, ALERT_ACTIONS, ALERT_ACTION_LABEL,
  createAlertRule, deleteAlertRule, evaluateAlerts, lastFiredAgo,
  listAlertRules, ruleSummary, updateAlertRule,
} from '@/lib/detection_alerts';

const { Text } = Typography;

export default function AlertRulesPage() {
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<AlertRule | null>(null);
  const [creating, setCreating] = useState(false);
  const [fires, setFires] = useState<AlertFire[] | null>(null);
  const [evaluating, setEvaluating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRules(await listAlertRules());
    } catch (e: any) {
      message.error(`加载失败: ${e?.message ?? e}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const doDelete = useCallback((r: AlertRule) => {
    Modal.confirm({
      title: `删除规则 "${r.name}"?`,
      onOk: async () => {
        try {
          await deleteAlertRule(r.id);
          message.success('已删除');
          await load();
        } catch (e: any) {
          message.error(`删除失败: ${e?.message ?? e}`);
        }
      },
    });
  }, [load]);

  const doToggle = useCallback(async (
    r: AlertRule, enabled: boolean,
  ) => {
    try {
      await updateAlertRule(r.id, { enabled });
      await load();
    } catch (e: any) {
      message.error(`更新失败: ${e?.message ?? e}`);
    }
  }, [load]);

  const doEvaluate = useCallback(async () => {
    setEvaluating(true);
    try {
      const r = await evaluateAlerts(3600);
      setFires(r.fires);
      if (r.fire_count === 0) {
        message.info('没有触发任何规则');
      } else {
        message.success(`触发 ${r.fire_count} 条告警`);
      }
      await load();
    } catch (e: any) {
      message.error(`评估失败: ${e?.message ?? e}`);
    } finally {
      setEvaluating(false);
    }
  }, [load]);

  const cols: ColumnsType<AlertRule> = [
    {
      title: '状态', dataIndex: 'enabled', width: 80,
      render: (v: boolean, r) => (
        <Switch checked={v} size="small"
          onChange={(v2) => void doToggle(r, v2)}
        />
      ),
    },
    { title: '名称', dataIndex: 'name', width: 180,
      render: (n: string) => <Text strong>{n}</Text> },
    { title: '条件', key: 'summary', render: (_, r) => ruleSummary(r) },
    {
      title: '动作', dataIndex: 'action', width: 100,
      render: (a: keyof typeof ALERT_ACTION_LABEL) => (
        <Tag color={a === 'feishu' ? 'blue' : a === 'sms' ? 'gold' : 'default'}>
          {ALERT_ACTION_LABEL[a]}
        </Tag>
      ),
    },
    {
      title: '最近触发', width: 120,
      render: (_, r) => (
        <Text type={r.last_fired_at ? 'warning' : 'secondary'}>
          {lastFiredAgo(r)}
        </Text>
      ),
    },
    {
      title: '操作', width: 140,
      render: (_, r) => (
        <Space size={4}>
          <Button size="small" onClick={() => setEditing(r)}>编辑</Button>
          <Button size="small" danger onClick={() => doDelete(r)}>
            删除
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 16 }}>
      <Typography.Title level={4}>
        🚨 检测告警规则
      </Typography.Title>

      <Card size="small" style={{ marginBottom: 12 }}>
        <Space>
          <Button type="primary" onClick={() => setCreating(true)}>
            + 新建规则
          </Button>
          <Button loading={evaluating} onClick={() => void doEvaluate()}>
            立即评估 (过去 1h)
          </Button>
          <Text type="secondary">
            规则用于监控 Vision Detection 聚类. 满足条件时触发日志 /
            飞书 / 短信通知.
          </Text>
        </Space>
      </Card>

      {fires && fires.length > 0 && (
        <Alert type="warning" showIcon closable
          style={{ marginBottom: 12 }}
          message={`触发了 ${fires.length} 条告警`}
          description={
            <Space direction="vertical" size={2}
              style={{ width: '100%' }}>
              {fires.map((f, i) => (
                <div key={i}>
                  <Tag color="red">{f.rule_name}</Tag>
                  <Text>
                    {f.label} × {f.member_count},
                    peak conf {f.peak_confidence.toFixed(2)} @
                    ({f.centroid_lat.toFixed(4)},{' '}
                    {f.centroid_lng.toFixed(4)})
                  </Text>
                </div>
              ))}
            </Space>
          }
          onClose={() => setFires(null)}
        />
      )}

      <Card size="small">
        {rules.length === 0 && !loading ? (
          <Empty description="尚未配置任何规则" />
        ) : (
          <Table<AlertRule>
            rowKey="id" size="small" loading={loading}
            columns={cols} dataSource={rules}
            pagination={false}
          />
        )}
      </Card>

      <RuleEditor
        open={creating}
        initial={null}
        onCancel={() => setCreating(false)}
        onSubmit={async (v) => {
          try {
            await createAlertRule(v);
            message.success('已创建');
            setCreating(false);
            await load();
          } catch (e: any) {
            message.error(`创建失败: ${e?.message ?? e}`);
          }
        }}
      />
      <RuleEditor
        open={editing !== null}
        initial={editing}
        onCancel={() => setEditing(null)}
        onSubmit={async (v) => {
          if (!editing) return;
          try {
            await updateAlertRule(editing.id, v);
            message.success('已更新');
            setEditing(null);
            await load();
          } catch (e: any) {
            message.error(`更新失败: ${e?.message ?? e}`);
          }
        }}
      />
    </div>
  );
}

function RuleEditor(props: {
  open: boolean;
  initial: AlertRule | null;
  onCancel: () => void;
  onSubmit: (v: any) => void | Promise<void>;
}) {
  const [form] = Form.useForm();
  useEffect(() => {
    if (props.open) {
      form.resetFields();
      if (props.initial) form.setFieldsValue(props.initial);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.open, props.initial]);

  return (
    <Modal
      open={props.open}
      title={props.initial ? '编辑规则' : '新建规则'}
      onCancel={props.onCancel}
      onOk={async () => {
        const v = await form.validateFields();
        await props.onSubmit(v);
      }}
      okText="保存"
      cancelText="取消"
    >
      <Form form={form} layout="vertical"
        initialValues={{
          min_member_count: 3, min_peak_confidence: 0,
          action: 'feishu', cooldown_seconds: 300,
        }}
      >
        <Form.Item name="name" label="规则名称"
          rules={[{ required: true, message: '必填' }]}>
          <Input placeholder="例: 人群聚集告警" />
        </Form.Item>
        <Form.Item name="label" label="检测类别 (* = 任意)"
          rules={[{ required: true, message: '必填' }]}>
          <Input placeholder="person / vehicle / fire / *" />
        </Form.Item>
        <Form.Item name="min_member_count" label="最小成员数"
          rules={[{ required: true }]}>
          <InputNumber min={1} max={1000} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="min_peak_confidence"
          label="最小峰值置信度 (0~1)">
          <InputNumber min={0} max={1} step={0.05}
            style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="action" label="触发动作"
          rules={[{ required: true }]}>
          <Select options={ALERT_ACTIONS.map((a) => ({
            label: ALERT_ACTION_LABEL[a], value: a,
          }))} />
        </Form.Item>
        <Form.Item name="cooldown_seconds" label="冷却时间 (秒)">
          <InputNumber min={0} max={86400} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="notes" label="备注">
          <Input.TextArea rows={2}
            placeholder="可选，记录规则用途" />
        </Form.Item>
      </Form>
    </Modal>
  );
}
