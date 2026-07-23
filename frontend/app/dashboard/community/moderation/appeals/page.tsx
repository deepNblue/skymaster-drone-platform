'use client';

/**
 * T6.16 — Appeal queue for moderators.
 *
 * Lists CommunityAppeal rows filed by post authors against auto-hide.
 * Admin/supervisor can:
 *   * Overturn → post restored to 'approved', auto-dismisses the
 *     open reports (T6.11 reporter rep hits the reporters).
 *   * Uphold → post stays hidden, no side effects.
 *
 * Only pending appeals surface by default; a segmented control lets
 * ops view historical decisions.
 */
import React, { useEffect, useState } from 'react';
import {
  App as AntApp,
  Button,
  Card,
  Empty,
  Input,
  Modal,
  Segmented,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from 'antd';
import { CheckOutlined, CloseOutlined } from '@ant-design/icons';
import { api } from '@/lib/api';

const { Title, Paragraph, Text } = Typography;

interface Appeal {
  id: string;
  post_id: string;
  author_id: string;
  note: string | null;
  status: 'pending' | 'upheld' | 'overturned';
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_note: string | null;
  created_at: string;
}

const STATUS_LABEL: Record<string, { color: string; text: string }> = {
  pending: { color: 'gold', text: '待审' },
  upheld: { color: 'red', text: '维持隐藏' },
  overturned: { color: 'green', text: '已恢复' },
};

export default function AppealsPage() {
  const { message } = AntApp.useApp();
  const [rows, setRows] = useState<Appeal[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<'pending' | 'all'>('pending');
  const [reviewOpen, setReviewOpen] = useState(false);
  const [target, setTarget] = useState<Appeal | null>(null);
  const [action, setAction] = useState<'uphold' | 'overturn'>('overturn');
  const [reviewNote, setReviewNote] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get('/api/v1/community/moderation/appeals', {
        params: filter === 'pending' ? { status: 'pending' } : {},
      });
      setRows(data.items);
    } catch (e: any) {
      message.error(`加载失败: ${e?.response?.data?.detail ?? e.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  const openReview = (row: Appeal, act: 'uphold' | 'overturn') => {
    setTarget(row);
    setAction(act);
    setReviewNote('');
    setReviewOpen(true);
  };

  const submitReview = async () => {
    if (!target) return;
    setSubmitting(true);
    try {
      await api.post(
        `/api/v1/community/moderation/appeals/${target.id}/resolve`,
        { action, review_note: reviewNote || undefined },
      );
      message.success(
        action === 'overturn'
          ? '已恢复该帖子并撤销相关举报'
          : '已维持隐藏决定',
      );
      setReviewOpen(false);
      load();
    } catch (e: any) {
      message.error(`提交失败: ${e?.response?.data?.detail ?? e.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: '0 auto' }}>
      <Title level={3}>社区申诉队列</Title>
      <Paragraph type="secondary">
        作者对 auto-hide 结果的申诉。
        <Text strong>恢复</Text>会同时撤销相关举报，
        举报人将扣减信誉分（T6.11）。
        <Text strong>维持</Text>则保持隐藏，不影响举报人分。
      </Paragraph>

      <Space style={{ marginBottom: 16 }}>
        <Segmented
          value={filter}
          options={[
            { label: '待审', value: 'pending' },
            { label: '全部', value: 'all' },
          ]}
          onChange={(v) => setFilter(v as 'pending' | 'all')}
        />
        <Button onClick={load}>刷新</Button>
      </Space>

      <Card>
        {loading ? (
          <div style={{ textAlign: 'center', padding: 40 }}>
            <Spin />
          </div>
        ) : rows.length === 0 ? (
          <Empty description="暂无申诉" />
        ) : (
          <Table
            rowKey="id"
            dataSource={rows}
            pagination={{ pageSize: 20 }}
            columns={[
              {
                title: '帖子',
                dataIndex: 'post_id',
                render: (v) => (
                  <a href={`/dashboard/community/${v}`} target="_blank" rel="noreferrer">
                    {v.slice(0, 8)}…
                  </a>
                ),
                width: 160,
              },
              {
                title: '作者',
                dataIndex: 'author_id',
                render: (v: string) => v?.slice(0, 8) ?? '-',
                width: 100,
              },
              {
                title: '申诉理由',
                dataIndex: 'note',
                render: (v: string | null) => v || <Text type="secondary">（无）</Text>,
                ellipsis: true,
              },
              {
                title: '状态',
                dataIndex: 'status',
                render: (v: string) => {
                  const s = STATUS_LABEL[v] ?? { color: 'default', text: v };
                  return <Tag color={s.color}>{s.text}</Tag>;
                },
                width: 100,
              },
              {
                title: '提交于',
                dataIndex: 'created_at',
                render: (v: string) => new Date(v).toLocaleString('zh-CN'),
                width: 170,
              },
              {
                title: '操作',
                render: (_v, row: Appeal) =>
                  row.status === 'pending' ? (
                    <Space>
                      <Button
                        size="small"
                        type="primary"
                        icon={<CheckOutlined />}
                        onClick={() => openReview(row, 'overturn')}
                      >
                        恢复
                      </Button>
                      <Button
                        size="small"
                        danger
                        icon={<CloseOutlined />}
                        onClick={() => openReview(row, 'uphold')}
                      >
                        维持
                      </Button>
                    </Space>
                  ) : (
                    <Text type="secondary">已处理</Text>
                  ),
                width: 180,
              },
            ]}
          />
        )}
      </Card>

      <Modal
        title={action === 'overturn' ? '恢复帖子' : '维持隐藏决定'}
        open={reviewOpen}
        onCancel={() => setReviewOpen(false)}
        onOk={submitReview}
        confirmLoading={submitting}
        okText="确认"
        cancelText="取消"
      >
        <Paragraph>
          {action === 'overturn' ? (
            <>
              将恢复帖子为「已通过」状态，并 <Text strong>自动撤销</Text> 该帖当前的所有开放举报。
              举报人将根据 T6.11 逻辑扣减信誉分。
            </>
          ) : (
            <>
              维持当前 auto-hide 结果，帖子保持隐藏状态。举报人的信誉分 <Text strong>不受影响</Text>。
            </>
          )}
        </Paragraph>
        <Input.TextArea
          rows={3}
          placeholder="审核备注（可选）"
          value={reviewNote}
          onChange={(e) => setReviewNote(e.target.value)}
          maxLength={500}
          showCount
        />
      </Modal>
    </div>
  );
}
