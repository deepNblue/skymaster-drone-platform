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
  type CommunityPost,
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
