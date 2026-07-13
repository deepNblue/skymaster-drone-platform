'use client';

/**
 * Community post detail page — v2.0 §3.18.
 * Path: /dashboard/community/[id]
 *
 * Layout:
 *   ┌───────────────────────────────┐
 *   │ Title + author + status tag   │
 *   │ Body (whitespace-preserved)   │
 *   │ Actions: Like / Copy link     │
 *   ├───────────────────────────────┤
 *   │ Comments list                 │
 *   │ Reply box                     │
 *   └───────────────────────────────┘
 */
import React, { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import {
  Card,
  Space,
  Tag,
  Typography,
  Button,
  Input,
  message,
  Spin,
  Divider,
  Avatar,
} from 'antd';
import {
  ArrowLeftOutlined,
  LikeOutlined,
  MessageOutlined,
  EyeOutlined,
  UserOutlined,
  SendOutlined,
} from '@ant-design/icons';
import {
  getCommunityPost,
  listCommunityComments,
  createCommunityComment,
  likeCommunityPost,
  CommunityPost,
  CommunityComment,
  ModerationStatus,
} from '@/lib/community';

const { Title, Text, Paragraph } = Typography;

const STATUS_TAG: Record<ModerationStatus, { color: string; label: string }> = {
  approved: { color: 'success', label: '已通过' },
  pending: { color: 'processing', label: '待审' },
  rejected: { color: 'error', label: '已拒绝' },
  archived: { color: 'default', label: '已归档' },
};

export default function CommunityPostPage() {
  const params = useParams();
  const router = useRouter();
  const pid = params?.id as string;

  const [post, setPost] = useState<CommunityPost | null>(null);
  const [comments, setComments] = useState<CommunityComment[]>([]);
  const [loading, setLoading] = useState(true);
  const [reply, setReply] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [p, cs] = await Promise.all([
        getCommunityPost(pid),
        listCommunityComments(pid),
      ]);
      setPost(p);
      setComments(cs);
    } catch (e: any) {
      message.error(`加载失败: ${e?.response?.data?.detail ?? e.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (pid) load();
  }, [pid]);

  const handleLike = async () => {
    if (!post) return;
    try {
      const p = await likeCommunityPost(post.id);
      setPost(p);
    } catch (e: any) {
      message.error(`点赞失败: ${e?.response?.data?.detail ?? e.message}`);
    }
  };

  const handleReply = async () => {
    if (!post || !reply.trim()) return;
    setSubmitting(true);
    try {
      const c = await createCommunityComment(post.id, reply.trim());
      if (c.moderation_status === 'rejected') {
        message.warning('评论被拒绝：命中受限关键词');
      } else if (c.moderation_status === 'pending') {
        message.info('评论已提交，等待人工审核');
      } else {
        message.success('评论发布成功');
      }
      setReply('');
      load();
    } catch (e: any) {
      message.error(`评论失败: ${e?.response?.data?.detail ?? e.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: 'center' }}>
        <Spin />
      </div>
    );
  }
  if (!post) {
    return (
      <div style={{ padding: 40, textAlign: 'center' }}>
        <Text type="secondary">帖子不存在或已被删除。</Text>
        <br />
        <Button
          type="link"
          onClick={() => router.push('/dashboard/community')}
        >
          返回列表
        </Button>
      </div>
    );
  }

  const badge = STATUS_TAG[post.moderation_status];

  return (
    <div style={{ padding: 16, maxWidth: 900, margin: '0 auto' }}>
      <Button
        type="link"
        icon={<ArrowLeftOutlined />}
        style={{ paddingLeft: 0, marginBottom: 8 }}
        onClick={() => router.push('/dashboard/community')}
      >
        返回列表
      </Button>

      <Card>
        <Title level={3} style={{ marginBottom: 8 }}>
          {post.title}
          {post.moderation_status !== 'approved' && (
            <Tag color={badge.color} style={{ marginLeft: 8, fontSize: 12 }}>
              {badge.label}
            </Tag>
          )}
        </Title>
        <Space split={<Divider type="vertical" />} style={{ marginBottom: 16 }}>
          <Space size={4}>
            <Avatar size={20} icon={<UserOutlined />} />
            <Text type="secondary" style={{ fontSize: 12 }}>
              {post.author_id ? post.author_id.slice(0, 8) : '匿名'}
            </Text>
          </Space>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {new Date(post.created_at).toLocaleString('zh-CN')}
          </Text>
          <Space size={4}>
            <EyeOutlined />
            <Text type="secondary" style={{ fontSize: 12 }}>
              {post.view_count}
            </Text>
          </Space>
        </Space>

        {post.moderation_status === 'rejected' && post.moderation_reason && (
          <Card
            size="small"
            style={{ background: '#fff2f0', borderColor: '#ffccc7', marginBottom: 12 }}
          >
            <Text type="danger" style={{ fontSize: 12 }}>
              该帖被拒绝：{post.moderation_reason}
            </Text>
          </Card>
        )}

        <Paragraph
          style={{
            whiteSpace: 'pre-wrap',
            fontSize: 14,
            lineHeight: 1.8,
          }}
        >
          {post.body}
        </Paragraph>

        {(post.tags ?? []).length > 0 && (
          <div style={{ marginTop: 8 }}>
            {(post.tags ?? []).map((t) => (
              <Tag key={t}>#{t}</Tag>
            ))}
          </div>
        )}

        <Divider />

        <Space>
          <Button icon={<LikeOutlined />} onClick={handleLike}>
            点赞 {post.like_count > 0 ? `(${post.like_count})` : ''}
          </Button>
          <Button
            onClick={() => {
              navigator.clipboard.writeText(
                `${window.location.origin}/dashboard/community/${post.id}`,
              );
              message.success('链接已复制');
            }}
          >
            复制链接
          </Button>
        </Space>
      </Card>

      <Card
        style={{ marginTop: 12 }}
        title={
          <Space>
            <MessageOutlined />
            <span>评论 · {comments.length}</span>
          </Space>
        }
      >
        {comments.length === 0 ? (
          <Text type="secondary">还没有评论，抢个沙发？</Text>
        ) : (
          comments.map((c) => (
            <div
              key={c.id}
              style={{
                padding: '8px 0',
                borderBottom: '1px solid #f0f0f0',
              }}
            >
              <Space size={6}>
                <Avatar size={22} icon={<UserOutlined />} />
                <Text strong style={{ fontSize: 12 }}>
                  {c.author_id ? c.author_id.slice(0, 8) : '匿名'}
                </Text>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  {new Date(c.created_at).toLocaleString('zh-CN')}
                </Text>
              </Space>
              <Paragraph style={{ marginTop: 4, marginBottom: 0, fontSize: 13 }}>
                {c.body}
              </Paragraph>
            </div>
          ))
        )}

        <Divider />

        <Input.TextArea
          rows={3}
          value={reply}
          onChange={(e) => setReply(e.target.value)}
          placeholder="友善发言，理性讨论"
          maxLength={4000}
          showCount
        />
        <div style={{ textAlign: 'right', marginTop: 8 }}>
          <Button
            type="primary"
            icon={<SendOutlined />}
            loading={submitting}
            disabled={!reply.trim()}
            onClick={handleReply}
          >
            发表评论
          </Button>
        </div>
      </Card>
    </div>
  );
}
