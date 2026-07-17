'use client';

/**
 * E2.7c · Pricing plans CRUD for a single listing.
 *
 * Route: /dashboard/marketplace-monetization/listing/[lid]/pricing
 * Vendor edits the pricing plans attached to their listing.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import {
  Alert, Button, Card, Descriptions, Form, Input, InputNumber, Modal,
  Select, Space, Switch, Table, Tag, Typography, message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined,
  RiseOutlined,
} from '@ant-design/icons';

import {
  BillingMode, ListingPrice, UpsertPricePayload,
  bpsToPercent, centsToYuan, getRevenue, listPrices,
  retirePrice, upsertPrice,
} from '@/lib/marketplace_monetization';

const { Title, Paragraph, Text } = Typography;

const MODE_LABEL: Record<BillingMode, string> = {
  one_off: '一次性', subscription: '订阅',
  metered: '按量', free_trial: '试用',
};
const MODE_COLOR: Record<BillingMode, string> = {
  one_off: 'geekblue', subscription: 'green',
  metered: 'gold', free_trial: 'default',
};

export default function PricingPlansPage() {
  const params = useParams<{ lid: string }>();
  const router = useRouter();
  const lid = params.lid;

  const [rows, setRows] = useState<ListingPrice[]>([]);
  const [loading, setLoading] = useState(false);
  const [includeRetired, setIncludeRetired] = useState(false);

  const [editing, setEditing] = useState<ListingPrice | null>(null);
  const [creating, setCreating] = useState(false);
  const [form] = Form.useForm<UpsertPricePayload>();

  const [revenue, setRevenue] = useState<{
    paid_orders: number; gross: number;
    fee: number; payout: number;
  } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await listPrices(lid, includeRetired));
      const r = await getRevenue(lid);
      setRevenue({
        paid_orders: r.paid_orders,
        gross: r.gross_cny_cents,
        fee: r.platform_fee_cny_cents,
        payout: r.vendor_payout_cny_cents,
      });
    } catch (e: any) {
      message.error(`加载失败: ${e?.message ?? e}`);
    } finally {
      setLoading(false);
    }
  }, [lid, includeRetired]);

  useEffect(() => { void load(); }, [load]);

  const openCreate = () => {
    setEditing(null);
    setCreating(true);
    form.resetFields();
    form.setFieldsValue({
      billing_mode: 'one_off',
      unit_price_cny_cents: 0,
      included_quota: 0,
      platform_fee_bps: 1500,
    });
  };

  const openEdit = (row: ListingPrice) => {
    setEditing(row);
    setCreating(false);
    form.setFieldsValue({
      plan_code: row.plan_code,
      plan_name: row.plan_name,
      billing_mode: row.billing_mode,
      unit_price_cny_cents: row.unit_price_cny_cents,
      included_quota: row.included_quota,
      billing_cycle_days: row.billing_cycle_days ?? undefined,
      platform_fee_bps: row.platform_fee_bps,
      note: row.note ?? undefined,
    });
  };

  const closeModal = () => {
    setEditing(null);
    setCreating(false);
    form.resetFields();
  };

  const onSubmit = useCallback(async () => {
    let vals: UpsertPricePayload;
    try { vals = await form.validateFields(); } catch { return; }
    try {
      await upsertPrice(lid, vals);
      message.success(editing ? '已更新' : '已创建');
      closeModal();
      await load();
    } catch (e: any) {
      message.error(`保存失败: ${e?.message ?? e}`);
    }
  }, [form, lid, editing, load]);

  const onRetire = useCallback(async (row: ListingPrice) => {
    Modal.confirm({
      title: `下架计划 ${row.plan_code}?`,
      content:
        '软删除, 历史订单仍保留价格记录. 新订单不能选择此计划.',
      okText: '下架',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try {
          await retirePrice(row.id);
          message.success('已下架');
          await load();
        } catch (e: any) {
          message.error(`下架失败: ${e?.message ?? e}`);
        }
      },
    });
  }, [load]);

  const modeChange = (v: BillingMode) => {
    // For subscription, ensure a sensible default cycle.
    if (v === 'subscription') {
      const cur = form.getFieldValue('billing_cycle_days');
      if (!cur) form.setFieldValue('billing_cycle_days', 30);
    }
  };

  const cols: ColumnsType<ListingPrice> = [
    {
      title: 'plan_code', dataIndex: 'plan_code', width: 140,
      render: (v: string, r: ListingPrice) => (
        <Space direction="vertical" size={0}>
          <Text strong>{v}</Text>
          <Text type="secondary" style={{ fontSize: 11 }}>
            {r.plan_name}
          </Text>
        </Space>
      ),
    },
    {
      title: '计费方式', dataIndex: 'billing_mode', width: 90,
      render: (v: BillingMode) => (
        <Tag color={MODE_COLOR[v]}>{MODE_LABEL[v]}</Tag>
      ),
    },
    {
      title: '单价', width: 100, align: 'right',
      render: (_: any, r: ListingPrice) => (
        <Text strong>{centsToYuan(r.unit_price_cny_cents)}</Text>
      ),
    },
    {
      title: '含量额度', dataIndex: 'included_quota', width: 90,
      align: 'right',
      render: (v: number) => v === 0 ? '—' : v.toLocaleString(),
    },
    {
      title: '周期(天)', dataIndex: 'billing_cycle_days', width: 80,
      align: 'right', render: (v: number | null) => v ?? '—',
    },
    {
      title: '平台抽成', dataIndex: 'platform_fee_bps', width: 90,
      align: 'right',
      render: (v: number) => (
        <Text type="secondary">{bpsToPercent(v)}</Text>
      ),
    },
    {
      title: '状态', dataIndex: 'retired', width: 80,
      render: (v: boolean) => v
        ? <Tag color="red">已下架</Tag>
        : <Tag color="green">在售</Tag>,
    },
    {
      title: '备注', dataIndex: 'note',
      render: (v: string | null) => v ?? <Text type="secondary">—</Text>,
    },
    {
      title: '操作', width: 160, fixed: 'right',
      render: (_: any, r: ListingPrice) => (
        <Space size={4}>
          <Button size="small" icon={<EditOutlined />}
            onClick={() => openEdit(r)}
            disabled={r.retired}
          >编辑</Button>
          {!r.retired && (
            <Button size="small" danger icon={<DeleteOutlined />}
              onClick={() => void onRetire(r)}
            >下架</Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 16 }}>
      <Space style={{ marginBottom: 8 }}>
        <Button onClick={() => router.back()}>← 返回</Button>
        <Title level={4} style={{ margin: 0 }}>
          定价计划管理
        </Title>
      </Space>
      <Paragraph type="secondary">
        Listing <Text code>{lid}</Text> 的定价计划。
        修改现有 plan_code 会覆盖当前价格；下架后仅软删除，历史订单保留完整价格记录。
      </Paragraph>

      {revenue && (
        <Alert
          type="success" showIcon style={{ marginBottom: 12 }}
          icon={<RiseOutlined />}
          message={
            <Space size="large">
              <span>累计成交 <Text strong>{revenue.paid_orders}</Text> 单</span>
              <span>总营业额 <Text strong>{centsToYuan(revenue.gross)}</Text></span>
              <span>平台费 {centsToYuan(revenue.fee)}</span>
              <span>Vendor 净收入
                <Text strong style={{ color: '#389e0d', marginLeft: 4 }}>
                  {centsToYuan(revenue.payout)}
                </Text>
              </span>
            </Space>
          }
        />
      )}

      <Space style={{ marginBottom: 8 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新增计划
        </Button>
        <Button icon={<ReloadOutlined />} onClick={() => void load()}>
          刷新
        </Button>
        <Text type="secondary">包含已下架</Text>
        <Switch
          checked={includeRetired}
          onChange={setIncludeRetired}
          size="small"
        />
      </Space>

      <Card size="small" bodyStyle={{ padding: 4 }}>
        <Table<ListingPrice>
          rowKey="id"
          columns={cols}
          dataSource={rows}
          loading={loading}
          size="small"
          pagination={false}
          scroll={{ x: 1100 }}
        />
      </Card>

      <Modal
        title={editing ? `编辑计划 ${editing.plan_code}` : '新增定价计划'}
        open={editing !== null || creating}
        onCancel={closeModal}
        onOk={onSubmit}
        okText="保存"
        cancelText="取消"
        width={640}
      >
        <Form form={form} layout="vertical">
          <Space.Compact block>
            <Form.Item
              name="plan_code" label="plan_code"
              rules={[{ required: true, min: 1, max: 64 }]}
              style={{ flex: 1 }}
            >
              <Input placeholder="monthly / metered_1k / trial_7d"
                disabled={editing !== null} />
            </Form.Item>
            <Form.Item
              name="plan_name" label="展示名"
              rules={[{ required: true, min: 1, max: 128 }]}
              style={{ flex: 1, marginLeft: 8 }}
            >
              <Input placeholder="月度订阅 / 千次调用包 / 7 天试用" />
            </Form.Item>
          </Space.Compact>

          <Form.Item
            name="billing_mode" label="计费方式"
            rules={[{ required: true }]}
          >
            <Select
              onChange={modeChange}
              options={(['one_off', 'subscription', 'metered', 'free_trial'] as BillingMode[]).map(
                (v) => ({ value: v, label: MODE_LABEL[v] }),
              )}
            />
          </Form.Item>

          <Space.Compact block>
            <Form.Item
              name="unit_price_cny_cents"
              label="单价 (分, 100分=1元)"
              rules={[{ required: true, type: 'number', min: 0 }]}
              style={{ flex: 1 }}
            >
              <InputNumber min={0} style={{ width: '100%' }} step={100} />
            </Form.Item>
            <Form.Item
              name="included_quota" label="包含调用次数 (metered)"
              style={{ flex: 1, marginLeft: 8 }}
            >
              <InputNumber min={0} style={{ width: '100%' }} step={1000} />
            </Form.Item>
          </Space.Compact>

          <Space.Compact block>
            <Form.Item
              name="billing_cycle_days" label="计费周期 (天, subscription 必填)"
              style={{ flex: 1 }}
            >
              <InputNumber min={1} max={365} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item
              name="platform_fee_bps"
              label="平台抽成 (bps, 100=1%)"
              rules={[{ required: true, type: 'number', min: 0, max: 10000 }]}
              style={{ flex: 1, marginLeft: 8 }}
            >
              <InputNumber min={0} max={10000} style={{ width: '100%' }} step={100} />
            </Form.Item>
          </Space.Compact>

          <Form.Item name="note" label="备注 (可选)">
            <Input.TextArea rows={2}
              placeholder="促销/内部说明, 不展示给购买方" />
          </Form.Item>
        </Form>

        {editing && (
          <Descriptions size="small" bordered column={2}
            style={{ marginTop: 12 }}
          >
            <Descriptions.Item label="ID">
              <Text code style={{ fontSize: 11 }}>{editing.id}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="创建于">
              {new Date(editing.created_at).toLocaleString('zh-CN')}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </div>
  );
}
