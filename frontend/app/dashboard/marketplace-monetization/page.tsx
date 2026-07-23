'use client';

/**
 * E2.7 · Marketplace monetization dashboard.
 *
 * Two panels side-by-side:
 *   1. My orders (this org bought)
 *   2. Revenue by listing (what a vendor gets paid)
 *
 * Pricing plan CRUD lives on a per-listing sub-page — this page is the
 * finance/ops overview.
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert, Button, Card, Col, Descriptions, Empty, Form, Input, InputNumber,
  Modal, Row, Select, Space, Statistic, Table, Tabs, Tag, Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  CheckCircleOutlined, CloseCircleOutlined, DollarOutlined,
  RollbackOutlined, ReloadOutlined,
} from '@ant-design/icons';

import {
  BillingMode, OrderStatus, PurchaseOrder,
  RevenueRollup,
  bpsToPercent, cancelOrder, centsToYuan,
  getRevenue, listOrders, payOrder, refundOrder,
} from '@/lib/marketplace_monetization';

const { Title, Text, Paragraph } = Typography;

const STATUS_COLOR: Record<OrderStatus, string> = {
  pending: 'orange',
  paid: 'green',
  cancelled: 'default',
  refunded: 'blue',
};
const STATUS_LABEL: Record<OrderStatus, string> = {
  pending: '待支付',
  paid: '已支付',
  cancelled: '已取消',
  refunded: '已退款',
};
const MODE_LABEL: Record<BillingMode, string> = {
  one_off: '一次性',
  subscription: '订阅',
  metered: '按量',
  free_trial: '试用',
};

export default function MarketplaceMonetizationPage() {
  const [orders, setOrders] = useState<PurchaseOrder[]>([]);
  const [orderLoading, setOrderLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<OrderStatus | undefined>();

  const [payingId, setPayingId] = useState<string | null>(null);
  const [payForm] = Form.useForm();

  const [revenueId, setRevenueId] = useState('');
  const [revenue, setRevenue] = useState<RevenueRollup | null>(null);
  const [revenueLoading, setRevenueLoading] = useState(false);

  const loadOrders = useCallback(async () => {
    setOrderLoading(true);
    try {
      const rows = await listOrders({ status: statusFilter });
      setOrders(rows);
    } catch (e: any) {
      message.error(`加载订单失败: ${e?.message ?? e}`);
    } finally {
      setOrderLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => { void loadOrders(); }, [loadOrders]);

  const doPay = useCallback(async () => {
    if (!payingId) return;
    let vals: any;
    try { vals = await payForm.validateFields(); } catch { return; }
    try {
      await payOrder(payingId, vals.external_ref || null);
      message.success('已标记为已支付');
      setPayingId(null);
      payForm.resetFields();
      await loadOrders();
    } catch (e: any) {
      message.error(`支付失败: ${e?.message ?? e}`);
    }
  }, [payingId, payForm, loadOrders]);

  const doCancel = useCallback(async (id: string) => {
    try {
      await cancelOrder(id);
      message.success('已取消');
      await loadOrders();
    } catch (e: any) {
      message.error(`取消失败: ${e?.message ?? e}`);
    }
  }, [loadOrders]);

  const doRefund = useCallback(async (id: string) => {
    try {
      await refundOrder(id);
      message.success('已退款');
      await loadOrders();
    } catch (e: any) {
      message.error(`退款失败: ${e?.message ?? e}`);
    }
  }, [loadOrders]);

  const loadRevenue = useCallback(async () => {
    if (!revenueId.trim()) {
      message.warning('请输入 listing UUID');
      return;
    }
    setRevenueLoading(true);
    try {
      setRevenue(await getRevenue(revenueId.trim()));
    } catch (e: any) {
      message.error(`加载收入失败: ${e?.message ?? e}`);
    } finally {
      setRevenueLoading(false);
    }
  }, [revenueId]);

  const orderCols: ColumnsType<PurchaseOrder> = [
    {
      title: '状态', dataIndex: 'status', width: 90,
      render: (v: OrderStatus) => (
        <Tag color={STATUS_COLOR[v]}>{STATUS_LABEL[v]}</Tag>
      ),
    },
    {
      title: 'plan', dataIndex: 'plan_code', width: 140,
      render: (v: string, r: PurchaseOrder) => (
        <Space direction="vertical" size={0}>
          <Text style={{ fontSize: 12 }}>{v}</Text>
          <Text type="secondary" style={{ fontSize: 11 }}>
            {MODE_LABEL[r.billing_mode]}
          </Text>
        </Space>
      ),
    },
    {
      title: '数量', dataIndex: 'units', width: 60, align: 'right',
    },
    {
      title: '总额', width: 100, align: 'right',
      render: (_: any, r: PurchaseOrder) => (
        <Text strong>{centsToYuan(r.total_cny_cents)}</Text>
      ),
    },
    {
      title: '平台费', width: 100, align: 'right',
      render: (_: any, r: PurchaseOrder) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {centsToYuan(r.platform_fee_cny_cents)}
        </Text>
      ),
    },
    {
      title: 'vendor 收入', width: 110, align: 'right',
      render: (_: any, r: PurchaseOrder) => (
        <Text style={{ color: '#389e0d' }}>
          {centsToYuan(r.vendor_payout_cny_cents)}
        </Text>
      ),
    },
    {
      title: '外部凭证', dataIndex: 'external_ref', width: 140,
      render: (v: string | null) => v ?? '—',
    },
    {
      title: '到期', width: 140,
      render: (_: any, r: PurchaseOrder) =>
        r.expires_at
          ? new Date(r.expires_at).toLocaleString('zh-CN')
          : '—',
    },
    {
      title: '操作', width: 200, fixed: 'right',
      render: (_: any, r: PurchaseOrder) => {
        if (r.status === 'pending') {
          return (
            <Space size={4}>
              <Button size="small" type="primary"
                icon={<DollarOutlined />}
                onClick={() => setPayingId(r.id)}>支付</Button>
              <Button size="small" danger
                icon={<CloseCircleOutlined />}
                onClick={() => void doCancel(r.id)}>取消</Button>
            </Space>
          );
        }
        if (r.status === 'paid') {
          return (
            <Button size="small" icon={<RollbackOutlined />}
              onClick={() => void doRefund(r.id)}>退款</Button>
          );
        }
        return null;
      },
    },
  ];

  return (
    <div style={{ padding: 16 }}>
      <Title level={4}>模型市场 · 交易与收入</Title>
      <Paragraph type="secondary">
        管理本机构在模型市场的采购订单，以及作为 vendor 时的收入总账。
        支付/取消/退款均为本地状态机变更，实际支付走 external_ref
        字段记录第三方（支付宝/微信/对公转账）凭证号。
      </Paragraph>

      <Tabs
        defaultActiveKey="orders"
        items={[
          {
            key: 'orders',
            label: '我的采购订单',
            children: (
              <>
                <Space style={{ marginBottom: 8 }}>
                  <Text type="secondary">状态:</Text>
                  <Select
                    allowClear placeholder="全部"
                    style={{ width: 120 }}
                    value={statusFilter}
                    onChange={setStatusFilter}
                    options={
                      (['pending', 'paid', 'cancelled', 'refunded'] as OrderStatus[])
                        .map(s => ({ value: s, label: STATUS_LABEL[s] }))
                    }
                  />
                  <Button icon={<ReloadOutlined />} onClick={() => void loadOrders()}>
                    刷新
                  </Button>
                </Space>
                <Card size="small" bodyStyle={{ padding: 4 }}>
                  <Table<PurchaseOrder>
                    rowKey="id"
                    columns={orderCols}
                    dataSource={orders}
                    loading={orderLoading}
                    size="small"
                    pagination={{ pageSize: 20, showSizeChanger: false }}
                    scroll={{ x: 1200 }}
                    locale={{ emptyText: <Empty description="暂无订单" /> }}
                  />
                </Card>
              </>
            ),
          },
          {
            key: 'revenue',
            label: 'Vendor 收入总账',
            children: (
              <>
                <Alert
                  type="info" showIcon style={{ marginBottom: 12 }}
                  message="按 Listing 查询"
                  description="输入某个 listing 的 UUID, 查询该 listing 所有已支付订单的收入分成汇总。"
                />
                <Space.Compact style={{ width: 400, marginBottom: 12 }}>
                  <Input
                    placeholder="listing UUID (36 chars)"
                    value={revenueId}
                    onChange={(e) => setRevenueId(e.target.value)}
                  />
                  <Button
                    type="primary"
                    loading={revenueLoading}
                    onClick={() => void loadRevenue()}
                    icon={<DollarOutlined />}
                  >查询</Button>
                </Space.Compact>

                {revenue && (
                  <Card size="small">
                    <Row gutter={16}>
                      <Col span={6}>
                        <Statistic
                          title="已支付订单"
                          value={revenue.paid_orders}
                          prefix={<CheckCircleOutlined style={{ color: '#52c41a' }} />}
                        />
                      </Col>
                      <Col span={6}>
                        <Statistic
                          title="总营业额 (¥)"
                          value={(revenue.gross_cny_cents / 100).toFixed(2)}
                        />
                      </Col>
                      <Col span={6}>
                        <Statistic
                          title="平台费 (¥)"
                          value={(revenue.platform_fee_cny_cents / 100).toFixed(2)}
                          valueStyle={{ color: '#8c8c8c' }}
                        />
                      </Col>
                      <Col span={6}>
                        <Statistic
                          title="Vendor 净收入 (¥)"
                          value={(revenue.vendor_payout_cny_cents / 100).toFixed(2)}
                          valueStyle={{ color: '#389e0d' }}
                        />
                      </Col>
                    </Row>
                    <Descriptions size="small" style={{ marginTop: 12 }} column={1}>
                      <Descriptions.Item label="Listing ID">
                        <Text code>{revenue.listing_id}</Text>
                      </Descriptions.Item>
                      <Descriptions.Item label="实际抽成率">
                        {revenue.gross_cny_cents > 0
                          ? bpsToPercent(Math.round(
                              revenue.platform_fee_cny_cents * 10000
                                / revenue.gross_cny_cents,
                            ))
                          : '—'}
                      </Descriptions.Item>
                    </Descriptions>
                  </Card>
                )}
              </>
            ),
          },
        ]}
      />

      {/* Pay Modal */}
      <Modal
        title="标记订单为已支付"
        open={payingId !== null}
        onCancel={() => { setPayingId(null); payForm.resetFields(); }}
        onOk={doPay}
        okText="确认支付"
        cancelText="取消"
      >
        <Form form={payForm} layout="vertical">
          <Form.Item
            name="external_ref"
            label="第三方支付凭证号"
            help="支付宝/微信/银行流水号, 便于日后对账. 可留空."
          >
            <Input placeholder="ALIPAY-2026-000123" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
