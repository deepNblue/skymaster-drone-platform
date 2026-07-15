'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Card,
  Tag,
  Table,
  Segmented,
  Typography,
  Button,
  Space,
  message,
} from 'antd';
import { FireOutlined } from '@ant-design/icons';
import {
  listMyPosts,
  getMyReputation,
  type CommunityPost,
  type MyReputation,
} from '@/lib/community';

const { Title, Text } = Typography;

/**
 * T6.20 — /dashboard/community/mine
 *
 * Author-scoped view of every post I've written across all
 * moderation statuses. Powered by GET /api/v1/community/posts/mine.
 */
export default function MyPostsPage() {
  const router = useRouter();
  const [posts, setPosts] = useState<CommunityPost[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<'all' | 'approved' | 'pending' | 'rejected'>('all');
  // T6.21 — my reputation is loaded once on mount, silent on failure
  const [rep, setRep] = useState<MyReputation | null>(null);

  useEffect(() => {
    getMyReputation().then(setRep).catch(() => setRep(null));
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    listMyPosts({
      status_filter: filter === 'all' ? undefined : filter,
      limit: 100,
    })
      .then((r) => {
        if (!cancelled) setPosts(r.items);
      })
      .catch((e: any) => {
        message.error(`加载失败: ${e?.response?.data?.detail ?? e.message}`);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [filter]);

  const statusTag = (p: CommunityPost) => {
    if (p.moderation_status === 'approved') {
      return <Tag color="green">已发布</Tag>;
    }
    if (p.moderation_status === 'rejected') {
      return <Tag color="red">已驳回</Tag>;
    }
    // pending — check auto-hide reason
    if (
      p.moderation_reason &&
      p.moderation_reason.toString().startsWith('auto-hidden')
    ) {
      return <Tag color="orange">🚫 已自动隐藏</Tag>;
    }
    return <Tag color="gold">待审核</Tag>;
  };

  return (
    <div style={{ padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
        <Space direction="vertical" size={0}>
          <Title level={4} style={{ margin: 0 }}>
            <FireOutlined /> 我的发帖
          </Title>
          <Text type="secondary" style={{ fontSize: 12 }}>
            包含所有状态：已发布 / 待审核 / 已驳回 / 自动隐藏
          </Text>
        </Space>
        <Segmented
          options={[
            { label: '全部', value: 'all' },
            { label: '已发布', value: 'approved' },
            { label: '待审核', value: 'pending' },
            { label: '已驳回', value: 'rejected' },
          ]}
          value={filter}
          onChange={(v) => setFilter(v as any)}
        />
      </div>

      <Card size="small">
        {/* T6.21 — reporter reputation banner. Colour-coded by label so
            trusted reporters get positive reinforcement and suspects
            see why their reports are being weighted down. */}
        {rep && (
          <div style={{
            marginBottom: 12,
            padding: '8px 12px',
            background: rep.label === 'trusted'
              ? '#f6ffed'
              : rep.label === 'suspect' ? '#fff2f0' : '#f0f5ff',
            border: `1px solid ${
              rep.label === 'trusted' ? '#b7eb8f'
                : rep.label === 'suspect' ? '#ffccc7' : '#adc6ff'
            }`,
            borderRadius: 4,
            fontSize: 13,
          }}>
            <Space size="middle">
              <Tag color={
                rep.label === 'trusted' ? 'green'
                  : rep.label === 'suspect' ? 'red' : 'blue'
              }>
                {rep.label === 'trusted' ? '⭐ 可信举报者'
                  : rep.label === 'suspect' ? '⚠️ 举报受限' : '举报权重正常'}
              </Tag>
              <Text type="secondary">
                历史举报：{rep.resolved} 采纳 / {rep.dismissed} 驳回 · 当前权重 {rep.weight}
              </Text>
            </Space>
          </div>
        )}
        <Table
          rowKey="id"
          loading={loading}
          dataSource={posts}
          pagination={{ pageSize: 20 }}
          onRow={(record) => ({
            onClick: () =>
              router.push(`/dashboard/community/${record.id}`),
            style: { cursor: 'pointer' },
          })}
          columns={[
            {
              title: '标题',
              dataIndex: 'title',
              key: 'title',
              render: (t: string) => <b>{t}</b>,
            },
            {
              title: '状态',
              key: 'status',
              width: 130,
              render: (_: any, p: CommunityPost) => statusTag(p),
            },
            {
              title: '👍',
              dataIndex: 'like_count',
              key: 'like_count',
              width: 60,
            },
            {
              title: '💬',
              dataIndex: 'comment_count',
              key: 'comment_count',
              width: 60,
            },
            {
              title: '发布时间',
              dataIndex: 'created_at',
              key: 'created_at',
              width: 170,
              render: (t: string) => new Date(t).toLocaleString('zh-CN'),
            },
          ]}
        />
      </Card>
    </div>
  );
}
