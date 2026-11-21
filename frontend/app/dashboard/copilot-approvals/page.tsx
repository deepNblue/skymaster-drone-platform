'use client';

/**
 * 审批中心 · v2.1 E2.5 前端整合入口.
 *
 * 让 admin/org_admin/approver/owner 集中处理所有 org 内 pending 的
 * Task Chain 审批（不用一个个 chain 点进去）。
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert, Button, Card, Empty, Form, Input, Modal, Space, Table, Tag,
  Typography, message,
} from 'antd';
import {
  ReloadOutlined, PlayCircleOutlined, StopOutlined, SafetyOutlined,
} from '@ant-design/icons';
import Link from 'next/link';

import {
  Approval,
  decideApproval,
  listPendingApprovals,
  PendingApprovalItem,
} from '@/lib/copilot_task_chain';

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;


export default function ApprovalsPage() {
  const [rows, setRows] = useState<PendingApprovalItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [decideOpen, setDecideOpen] = useState(false);
  const [decideTarget, setDecideTarget] = useState<PendingApprovalItem | null>(null);
  const [decideAction, setDecideAction] = useState<'approved' | 'rejected'>('approved');
  const [decideReason, setDecideReason] = useState('');
  const [decideModsRaw, setDecideModsRaw] = useState('');
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const r = await listPendingApprovals(50);
      setRows(r.items);
    } catch (e: any) {
      message.error(`加载失败: ${e?.message ?? e}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const openDecide = (row: PendingApprovalItem, action: 'approved' | 'rejected') => {
    setDecideTarget(row);
    setDecideAction(action);
    setDecideReason('');
    setDecideModsRaw(row.approval.args_snapshot
      ? JSON.stringify(row.approval.args_snapshot, null, 2)
      : '',
    );
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
        message.error(`args JSON 解析失败: ${e?.message ?? e}`);
        return;
      }
    }
    setBusy(true);
    try {
      await decideApproval(
        decideTarget.approval.id,
        { decision: decideAction, reason: decideReason.trim(), modifications: mods },
        true,
      );
      message.success(decideAction === 'approved' ? '已批准' : '已拒绝');
      setDecideOpen(false);
      await reload();
    } catch (e: any) {
      message.error(`决策失败: ${e?.message ?? e}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ padding: 24 }}>
      <Title level={3}>
        <SafetyOutlined /> 审批中心
        <Text type="secondary" style={{ fontSize: 14, marginLeft: 12 }}>
          Copilot Task Chain · 高危工具审批门
        </Text>
      </Title>
      <Alert
        type="info" showIcon
        style={{ marginBottom: 16 }}
        message="只显示当前 org 内待审批的步骤。批准会立即 resume；拒绝会将 chain 置为 failed。"
      />

      <Card
        size="small"
        title={<>待审批 <Text type="secondary">({rows.length})</Text></>}
        extra={<Button icon={<ReloadOutlined />} size="small" onClick={reload} />}
      >
        {rows.length === 0 ? (
          <Empty description="没有等待审批的步骤" />
        ) : (
          <Table
            rowKey={(r) => r.approval.id}
            loading={loading}
            dataSource={rows}
            pagination={false}
            size="small"
            columns={[
              {
                title: '工具',
                dataIndex: ['approval', 'tool_name'],
                render: (_: any, r: PendingApprovalItem) => (
                  <Space size={4}>
                    <Tag color="red">{r.approval.risk_level}</Tag>
                    <Tag>{r.approval.permission}</Tag>
                    <Text code>{r.approval.tool_name}</Text>
                  </Space>
                ),
              },
              {
                title: 'Chain',
                render: (_: any, r: PendingApprovalItem) => (
                  <Link href={`/dashboard/copilot-task-chain?open=${r.chain.id}`}>
                    <Text ellipsis style={{ maxWidth: 260 }}>{r.chain.goal}</Text>
                  </Link>
                ),
              },
              {
                title: '步骤',
                render: (_: any, r: PendingApprovalItem) => (
                  <Text type="secondary">#{r.approval.step_index + 1}</Text>
                ),
              },
              {
                title: '需要审批的原因',
                dataIndex: ['approval', 'required_reason'],
                render: (v: string) => (
                  <Text type="secondary" style={{ fontSize: 12 }}>{v}</Text>
                ),
              },
              {
                title: '提交时间',
                dataIndex: ['approval', 'created_at'],
                render: (v: string) => v
                  ? <Text type="secondary" style={{ fontSize: 12 }}>{new Date(v).toLocaleString()}</Text>
                  : '-',
              },
              {
                title: '操作',
                render: (_: any, r: PendingApprovalItem) => (
                  <Space size={4}>
                    <Button
                      size="small" type="primary"
                      icon={<PlayCircleOutlined />}
                      onClick={() => openDecide(r, 'approved')}
                    >
                      批准
                    </Button>
                    <Button
                      size="small" danger
                      icon={<StopOutlined />}
                      onClick={() => openDecide(r, 'rejected')}
                    >
                      拒绝
                    </Button>
                  </Space>
                ),
              },
            ]}
          />
        )}
      </Card>

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
        confirmLoading={busy}
        width={640}
      >
        {decideTarget && (
          <div style={{ marginBottom: 12 }}>
            <Space>
              <Tag color="red">{decideTarget.approval.risk_level}</Tag>
              <Tag>{decideTarget.approval.permission}</Tag>
              <Text code>{decideTarget.approval.tool_name}</Text>
              <Text type="secondary">
                Chain: {decideTarget.chain.goal}
              </Text>
            </Space>
            <Paragraph type="secondary" style={{ margin: '6px 0' }}>
              {decideTarget.approval.required_reason}
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
