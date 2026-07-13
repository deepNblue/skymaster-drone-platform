'use client';

/**
 * V2ApprovalsInbox — T4.2 v2 审批工作台。
 *
 * 拉取 GET /api/v1/copilot/v2/approvals/pending。
 * 每条待审批展示：工具名 + 参数 + 会话上下文。
 * 支持：批准 / 驳回 / 按修改后参数执行。
 *
 * 独立于 v1 的 ApprovalsInbox；后端也是不同端点。
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  Card,
  List,
  Tag,
  Button,
  Space,
  Modal,
  Input,
  message as antdMessage,
  Empty,
  Typography,
  Badge,
  Popconfirm,
} from 'antd';
import {
  CheckOutlined,
  CloseOutlined,
  EditOutlined,
  ReloadOutlined,
  AuditOutlined,
} from '@ant-design/icons';
import {
  listV2PendingApprovals,
  decideV2Approval,
  V2PendingApproval,
} from '@/lib/copilot_v2';

const { Text } = Typography;

const SENSITIVE_TOOL_COLOR: Record<string, string> = {
  create_mission: 'orange',
  dispatch_mission: 'red',
  abort_mission: 'volcano',
  takeoff: 'red',
  land: 'orange',
  goto: 'blue',
  rtl: 'purple',
};

export default function V2ApprovalsInbox() {
  const [items, setItems] = useState<V2PendingApproval[]>([]);
  const [loading, setLoading] = useState(false);
  const [modifyOpen, setModifyOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [active, setActive] = useState<V2PendingApproval | null>(null);
  const [modifiedArgs, setModifiedArgs] = useState('');
  const [comment, setComment] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await listV2PendingApprovals(50);
      setItems(rows);
    } catch (e: any) {
      antdMessage.error('加载待审批失败：' + (e?.message || 'unknown'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, [load]);

  const approve = async (item: V2PendingApproval) => {
    try {
      await decideV2Approval(item.approval_id, { decision: 'approved' });
      antdMessage.success('已批准并执行');
      load();
    } catch (e: any) {
      antdMessage.error(e?.message || '批准失败');
    }
  };

  const reject = async () => {
    if (!active) return;
    try {
      await decideV2Approval(active.approval_id, {
        decision: 'rejected',
        comment: comment || undefined,
      });
      antdMessage.success('已驳回');
      setRejectOpen(false);
      setComment('');
      setActive(null);
      load();
    } catch (e: any) {
      antdMessage.error(e?.message || '驳回失败');
    }
  };

  const modify = async () => {
    if (!active) return;
    let parsed: Record<string, any>;
    try {
      parsed = JSON.parse(modifiedArgs);
    } catch {
      antdMessage.error('修改后的参数不是合法 JSON');
      return;
    }
    try {
      await decideV2Approval(active.approval_id, {
        decision: 'modified',
        modifications: parsed,
      });
      antdMessage.success('已按修改后参数执行');
      setModifyOpen(false);
      setActive(null);
      load();
    } catch (e: any) {
      antdMessage.error(e?.message || '按修改执行失败');
    }
  };

  return (
    <>
      <Card
        title={
          <Space>
            <AuditOutlined />
            <span>Copilot v2 敏感操作审批</span>
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
          <Button
            size="small"
            icon={<ReloadOutlined />}
            onClick={load}
            loading={loading}
          >
            刷新
          </Button>
        }
        style={{ height: '100%' }}
        styles={{
          body: { padding: 0, height: 'calc(100% - 56px)', overflow: 'auto' },
        }}
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
                    onConfirm={() => approve(item)}
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
                    key="modify"
                    size="small"
                    icon={<EditOutlined />}
                    onClick={() => {
                      setActive(item);
                      setModifiedArgs(
                        JSON.stringify(item.arguments || {}, null, 2),
                      );
                      setModifyOpen(true);
                    }}
                  >
                    修改
                  </Button>,
                  <Button
                    key="reject"
                    size="small"
                    danger
                    icon={<CloseOutlined />}
                    onClick={() => {
                      setActive(item);
                      setRejectOpen(true);
                    }}
                  >
                    驳回
                  </Button>,
                ]}
              >
                <List.Item.Meta
                  title={
                    <Space>
                      <Tag
                        color={
                          SENSITIVE_TOOL_COLOR[item.tool || ''] || 'default'
                        }
                      >
                        {item.tool || 'unknown'}
                      </Tag>
                      <Text code style={{ fontSize: 11 }}>
                        {item.approval_id.slice(0, 8)}
                      </Text>
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        {item.created_at
                          ? new Date(item.created_at).toLocaleTimeString()
                          : '-'}
                      </Text>
                    </Space>
                  }
                  description={
                    <div>
                      {item.prompt && (
                        <Text style={{ fontSize: 13, display: 'block' }}>
                          {item.prompt}
                        </Text>
                      )}
                      <pre
                        style={{
                          background: 'rgba(0,0,0,0.15)',
                          padding: 6,
                          borderRadius: 4,
                          fontSize: 11,
                          margin: '4px 0 0 0',
                          maxHeight: 120,
                          overflow: 'auto',
                        }}
                      >
                        {JSON.stringify(item.arguments || {}, null, 2)}
                      </pre>
                    </div>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Card>

      <Modal
        title={`按修改后参数执行：${active?.tool}`}
        open={modifyOpen}
        onOk={modify}
        onCancel={() => {
          setModifyOpen(false);
          setActive(null);
        }}
        okText="按修改执行"
        cancelText="取消"
        width={600}
      >
        <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
          修改后的完整参数会覆盖原始参数（deep merge），请确认无误后执行。
        </Text>
        <Input.TextArea
          rows={12}
          value={modifiedArgs}
          onChange={(e) => setModifiedArgs(e.target.value)}
          style={{ fontFamily: 'monospace', fontSize: 12 }}
        />
      </Modal>

      <Modal
        title={`驳回：${active?.tool}`}
        open={rejectOpen}
        onOk={reject}
        onCancel={() => {
          setRejectOpen(false);
          setComment('');
          setActive(null);
        }}
        okText="确认驳回"
        cancelText="取消"
        okButtonProps={{ danger: true }}
      >
        <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
          {active?.prompt}
        </Text>
        <Input.TextArea
          rows={3}
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="驳回原因（可选，将写入审计）"
        />
      </Modal>
    </>
  );
}
