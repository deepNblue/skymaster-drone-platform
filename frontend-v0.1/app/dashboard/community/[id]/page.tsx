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
  Modal,
  Select,
} from 'antd';
import {
  ArrowLeftOutlined,
  LikeOutlined,
  LikeFilled,
  MessageOutlined,
  EyeOutlined,
  UserOutlined,
  SendOutlined,
  FlagOutlined,
} from '@ant-design/icons';
import {
  getCommunityPost,
  listCommunityComments,
  createCommunityComment,
  likeCommunityPost,
  unlikeCommunityPost,
  reportPost,
  REPORT_REASONS,
  ReportReason,
  CommunityPost,
  CommunityComment,
  ModerationStatus,
} from '@/lib/community';
import { api } from '@/lib/api';

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
  const [reportOpen, setReportOpen] = useState(false);
  // T6.14 — track viewer role to conditionally show admin pin controls.
  const [meRole, setMeRole] = useState<string | null>(null);
  const [reportReason, setReportReason] = useState<ReportReason>('spam');
  const [reportNote, setReportNote] = useState('');
  const [reporting, setReporting] = useState(false);

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

  // T6.14 — pull viewer role once (admin only sees pin controls).
  useEffect(() => {
    import('@/lib/api').then(({ getMe }) =>
      getMe().then((u) => setMeRole(u.role)).catch(() => setMeRole(null))
    );
  }, []);

  // T6.14 — toggle pinned status; refresh post on success.
  const handleTogglePin = async () => {
    if (!post) return;
    try {
      const { pinCommunityPost } = await import('@/lib/community');
      const p = await pinCommunityPost(post.id, !post.pinned);
      setPost(p);
      message.success(p.pinned ? '已置顶' : '已取消置顶');
    } catch (e: any) {
      const status = e?.response?.status;
      if (status === 409) {
        message.warning('只能置顶已通过审核的帖子');
      } else {
        message.error(`置顶操作失败: ${e?.response?.data?.detail ?? e.message}`);
      }
    }
  };

  // T6.17 — toggle like state based on post.liked_by_me. Both handlers
  // return the fresh PostOut with the correct liked_by_me flag set, so
  // the heart button flips immediately without a re-fetch.
  const handleLike = async () => {
    if (!post) return;
    try {
      const p = post.liked_by_me
        ? await unlikeCommunityPost(post.id)
        : await likeCommunityPost(post.id);
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
          {post.pinned && (
            <Tag color="gold" style={{ marginLeft: 8, fontSize: 12 }}>
              📌 置顶
            </Tag>
          )}
          {post.moderation_status !== 'approved' && (
            <Tag color={badge.color} style={{ marginLeft: 8, fontSize: 12 }}>
              {badge.label}
            </Tag>
          )}
          {meRole === 'admin' && post.moderation_status === 'approved' && (
            <Button
              size="small"
              type={post.pinned ? 'default' : 'primary'}
              style={{ marginLeft: 12, fontSize: 12 }}
              onClick={handleTogglePin}
              title={post.pinned ? '取消置顶后此帖不再在列表页优先显示' : '置顶后此帖将排在社区列表最前'}
            >
              {post.pinned ? '取消置顶' : '📌 置顶'}
            </Button>
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

        {/* T6.16 — author-facing appeal card. Shown when the post has
            been auto-hidden by the reputation-weighted rule and the
            viewer is the author. */}
        {post.moderation_status === 'pending' &&
          post.moderation_reason?.startsWith('auto-hidden') && (
            <Card
              size="small"
              style={{
                background: '#fffbe6',
                borderColor: '#ffe58f',
                marginBottom: 12,
              }}
            >
              <Space direction="vertical" size={6} style={{ width: '100%' }}>
                <Text type="warning" style={{ fontSize: 12 }}>
                  该帖已被系统自动隐藏：{post.moderation_reason}
                </Text>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  如果认为是误判，可以提交申诉，管理员会人工复核。
                </Text>
                <Button
                  size="small"
                  onClick={async () => {
                    try {
                      const note = window.prompt('可选：申诉理由（留空可直接提交）') ?? undefined;
                      const { data } = await api.post(
                        `/api/v1/community/posts/${post.id}/appeal`,
                        { note },
                      );
                      message.success(`已提交申诉 #${data.id.slice(0, 8)}，等待管理员审核`);
                    } catch (e: any) {
                      const detail = e?.response?.data?.detail ?? e.message;
                      if (e?.response?.status === 409) {
                        message.warning(`无法提交：${detail}`);
                      } else {
                        message.error(`提交失败: ${detail}`);
                      }
                    }
                  }}
                >
                  📩 提交申诉
                </Button>
              </Space>
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
          <Button
            icon={post.liked_by_me ? <LikeFilled style={{ color: '#1677ff' }} /> : <LikeOutlined />}
            type={post.liked_by_me ? 'primary' : 'default'}
            onClick={handleLike}
          >
            {post.liked_by_me ? '已赞' : '点赞'} {post.like_count > 0 ? `(${post.like_count})` : ''}
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
          <Button
            icon={<FlagOutlined />}
            danger
            onClick={() => setReportOpen(true)}
          >
            举报
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

      <Modal
        title="举报此帖"
        open={reportOpen}
        onCancel={() => setReportOpen(false)}
        okText="提交举报"
        okButtonProps={{ danger: true, loading: reporting }}
        onOk={async () => {
          if (!post) return;
          setReporting(true);
          try {
            await reportPost(post.id, {
              reason: reportReason,
              note: reportNote || undefined,
            });
            message.success('举报已提交，管理员将尽快处理');
            setReportOpen(false);
            setReportNote('');
          } catch (e: any) {
            const d = e?.response?.data?.detail;
            if (e?.response?.status === 409) {
              message.warning('你已经举报过这个帖子了');
              setReportOpen(false);
            } else if (e?.response?.status === 400) {
              message.error('不能举报自己发布的帖子');
            } else {
              message.error(`举报失败: ${d ?? e.message}`);
            }
          } finally {
            setReporting(false);
          }
        }}
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            所有举报由管理员人工复核。恶意/重复举报可能影响你的账号信誉。
          </Text>
          <div>
            <Text strong>举报原因</Text>
            <Select
              style={{ width: '100%', marginTop: 4 }}
              value={reportReason}
              onChange={setReportReason}
              options={REPORT_REASONS.map((r) => ({
                value: r.value,
                label: r.label,
              }))}
            />
          </div>
          <div>
            <Text strong>补充说明（可选）</Text>
            <Input.TextArea
              rows={3}
              maxLength={1000}
              showCount
              placeholder="补充违规细节、时间戳、上下文等，帮助管理员判断"
              value={reportNote}
              onChange={(e) => setReportNote(e.target.value)}
              style={{ marginTop: 4 }}
            />
          </div>
        </Space>
      </Modal>
    </div>
  );
}
