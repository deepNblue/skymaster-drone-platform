'use client';

/**
 * ApprovalsInbox — v2.0 Copilot 审批工作台。
 *
 * 拉取 GET /copilot/approvals/pending，展示待审批 trace 列表。
 * 每条支持：批准 / 驳回 / 备注。操作后自动刷新列表。
 *
 * 挂载在 /dashboard/copilot 页面右侧。
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  Card, List, Tag, Button, Space, Modal, Input, message, Empty,
  Typography, Badge, Popconfirm, Checkbox,
} from 'antd';
import {
  CheckOutlined, CloseOutlined, ReloadOutlined, AuditOutlined,
} from '@ant-design/icons';
import { listPendingApprovals, approveTrace, bulkApproveTraces } from '@/lib/api';

const { Text } = Typography;

interface PendingItem {
  trace_id: string;
  session_id: string | null;
  org_id: string | null;
  org_name: string | null;
  intent: string | null;
  prompt: string;
  started_at: string | null;
  status: string;
}

const INTENT_COLOR: Record<string, string> = {
  takeoff: 'red',
  land: 'orange',
  goto: 'blue',
  rtl: 'purple',
  scan: 'geekblue',
  photo: 'cyan',
};

export default function ApprovalsInbox() {
  const [items, setItems] = useState<PendingItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [activeItem, setActiveItem] = useState<PendingItem | null>(null);
  const [comment, setComment] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAll = () => {
    if (selected.size === items.length) setSelected(new Set());
    else setSelected(new Set(items.map((i) => i.trace_id)));
  };

  const handleBulk = async (decision: 'approved' | 'rejected') => {
    if (selected.size === 0) return;
    try {
      const result = await bulkApproveTraces(
        Array.from(selected),
        decision,
      );
      message.success(
        `已${decision === 'approved' ? '批准' : '驳回'} ${result.processed}/${result.requested} 条`,
      );
      setSelected(new Set());
      load();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '批量操作失败');
    }
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await listPendingApprovals();
      setItems(rows);
    } catch (e: any) {
      message.error('加载失败：' + (e?.response?.data?.detail || e.message));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 15000);  // 15s 轮询
    return () => clearInterval(id);
  }, [load]);

  const handleApprove = async (item: PendingItem) => {
    try {
      await approveTrace(item.trace_id, 'approved');
      message.success('已批准');
      load();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '批准失败');
    }
  };

  const handleReject = async () => {
    if (!activeItem) return;
    try {
      await approveTrace(activeItem.trace_id, 'rejected', comment || undefined);
      message.success('已驳回');
      setRejectOpen(false);
      setComment('');
      setActiveItem(null);
      load();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '驳回失败');
    }
  };

  return (
    <Card
      title={
        <Space>
          <AuditOutlined />
          <span>Copilot 审批工作台</span>
          <Badge
            count={items.length}
            style={{
              backgroundColor: items.length > 0 ? '#faad14' : '#52c41a',
            }}
            showZero
          />
        </Space>
      }
      extra={
        <Space>
          {items.length > 0 && (
            <>
              <Button size="small" onClick={selectAll}>
                {selected.size === items.length ? '取消全选' : '全选'}
              </Button>
              <Button
                size="small"
                type="primary"
                disabled={selected.size === 0}
                onClick={() => handleBulk('approved')}
              >
                批准({selected.size})
              </Button>
              <Button
                size="small"
                danger
                disabled={selected.size === 0}
                onClick={() => handleBulk('rejected')}
              >
                驳回({selected.size})
              </Button>
            </>
          )}
          <Button
            size="small"
            icon={<ReloadOutlined />}
            onClick={load}
            loading={loading}
          >
            刷新
          </Button>
        </Space>
      }
      style={{ height: '100%' }}
      styles={{ body: { padding: 0, height: 'calc(100% - 56px)', overflow: 'auto' } }}
    >
      {items.length === 0 ? (
        <div style={{ padding: 48 }}>
          <Empty description="🎉 无待审批任务" />
        </div>
      ) : (
        <List
          dataSource={items}
          renderItem={(item) => (
            <List.Item
              style={{
                padding: '12px 16px',
                borderBottom: '1px solid var(--sm-border, #30363d)',
              }}
              actions={[
                <Popconfirm
                  key="approve"
                  title="确认批准并执行？"
                  onConfirm={() => handleApprove(item)}
                  okText="批准"
                  cancelText="取消"
                >
                  <Button
                    size="small"
                    type="primary"
                    icon={<CheckOutlined />}
                  >
                    批准
                  </Button>
                </Popconfirm>,
                <Button
                  key="reject"
                  size="small"
                  danger
                  icon={<CloseOutlined />}
                  onClick={() => {
                    setActiveItem(item);
                    setRejectOpen(true);
                  }}
                >
                  驳回
                </Button>,
              ]}
            >
              <List.Item.Meta
                avatar={
                  <Checkbox
                    checked={selected.has(item.trace_id)}
                    onChange={() => toggle(item.trace_id)}
                  />
                }
                title={
                  <Space>
                    <Tag color={INTENT_COLOR[item.intent || ''] || 'default'}>
                      {item.intent || 'unknown'}
                    </Tag>
                    {item.org_name && (
                      <Tag color="cyan" style={{ fontSize: 11 }}>
                        {item.org_name}
                      </Tag>
                    )}
                    <Text code style={{ fontSize: 11 }}>
                      {item.trace_id.slice(0, 8)}
                    </Text>
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      {item.started_at
                        ? new Date(item.started_at).toLocaleTimeString()
                        : '-'}
                    </Text>
                  </Space>
                }
                description={
                  <div>
                    <Text style={{ fontSize: 13 }}>{item.prompt}</Text>
                  </div>
                }
              />
            </List.Item>
          )}
        />
      )}

      <Modal
        title={`驳回 trace ${activeItem?.trace_id.slice(0, 8)}`}
        open={rejectOpen}
        onOk={handleReject}
        onCancel={() => {
          setRejectOpen(false);
          setComment('');
          setActiveItem(null);
        }}
        okText="确认驳回"
        cancelText="取消"
        okButtonProps={{ danger: true }}
      >
        <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
          {activeItem?.prompt}
        </Text>
        <Input.TextArea
          placeholder="驳回原因（可选，将记录到审计日志）"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          rows={3}
        />
      </Modal>
    </Card>
  );
}
