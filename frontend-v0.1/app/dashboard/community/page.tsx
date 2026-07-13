'use client';

/**
 * Community list page — v2.0 §3.18.
 *
 * Split into two panes:
 *   - Left: post list with tag filter + pinned + like counts.
 *   - Right: create-post drawer trigger + moderation queue link
 *            (admin only).
 *
 * Clicking a post row routes to /dashboard/community/[id].
 */
import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Card,
  List,
  Space,
  Tag,
  Typography,
  Button,
  Drawer,
  Input,
  Form,
  message,
  Spin,
  Empty,
  Alert,
  Segmented,
} from 'antd';
import {
  PlusOutlined,
  FireOutlined,
  MessageOutlined,
  LikeOutlined,
  EyeOutlined,
  PushpinFilled,
  SafetyOutlined,
} from '@ant-design/icons';
import {
  listCommunityPosts,
  createCommunityPost,
  CommunityPost,
  ModerationStatus,
} from '@/lib/community';
import { getMe } from '@/lib/api';

const { Title, Text, Paragraph } = Typography;

const STATUS_TAG: Record<ModerationStatus, { color: string; label: string }> = {
  approved: { color: 'success', label: '已通过' },
  pending: { color: 'processing', label: '待审' },
  rejected: { color: 'error', label: '已拒绝' },
  archived: { color: 'default', label: '已归档' },
};

export default function CommunityListPage() {
  const router = useRouter();
  const [posts, setPosts] = useState<CommunityPost[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [tag, setTag] = useState<string | undefined>();
  const [role, setRole] = useState<string | null>(null);
  const [form] = Form.useForm();

  useEffect(() => {
    getMe()
      .then((u: any) => setRole(u?.role ?? null))
      .catch(() => setRole(null));
  }, []);

  const reload = async (t?: string) => {
    setLoading(true);
    try {
      const res = await listCommunityPosts({ limit: 50, tag: t });
      setPosts(res.items);
      setTotal(res.total);
    } catch (e: any) {
      message.error(`加载失败: ${e?.response?.data?.detail ?? e.message}`);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    reload(tag);
  }, [tag]);

  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      setSubmitting(true);
      const p = await createCommunityPost({
        title: values.title,
        body: values.body,
        tags: values.tags
          ? values.tags.split(',').map((s: string) => s.trim()).filter(Boolean)
          : [],
      });
      if (p.moderation_status === 'rejected') {
        message.warning(`发帖被拒绝: ${p.moderation_reason ?? '内容命中限制词'}`);
      } else if (p.moderation_status === 'pending') {
        message.info('内容已提交，等待人工审核');
      } else {
        message.success('发布成功');
      }
      form.resetFields();
      setDrawerOpen(false);
      reload(tag);
    } catch (e: any) {
      if (e?.errorFields) return; // form validation
      message.error(`发布失败: ${e?.response?.data?.detail ?? e.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const tags = ['mission', 'review', 'qa', 'showcase', 'compliance'];

  return (
    <div style={{ padding: 16 }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 12,
        }}
      >
        <Space direction="vertical" size={0}>
          <Title level={4} style={{ margin: 0 }}>
            <FireOutlined /> 飞手社区
          </Title>
          <Text type="secondary">
            分享任务复盘、技术问答、合规经验。所有内容经关键词审核。
          </Text>
        </Space>
        <Space>
          {role === 'admin' && (
            <Button
              icon={<SafetyOutlined />}
              onClick={() => router.push('/dashboard/community/moderation')}
            >
              审核队列
            </Button>
          )}
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setDrawerOpen(true)}
          >
            发帖
          </Button>
        </Space>
      </div>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="社区规则"
        description="禁止发布涉军、暴恐、毒品、色情、违法内容。营销/私聊出售类信息将进入待审队列。首次违规视情节警告或封禁。"
      />

      <div style={{ marginBottom: 12 }}>
        <Segmented
          options={[
            { label: '全部', value: '__all__' },
            ...tags.map((t) => ({ label: `#${t}`, value: t })),
          ]}
          value={tag ?? '__all__'}
          onChange={(v) =>
            setTag((v as string) === '__all__' ? undefined : (v as string))
          }
        />
      </div>

      <Card size="small">
        {loading ? (
          <div style={{ textAlign: 'center', padding: 40 }}>
            <Spin />
          </div>
        ) : posts.length === 0 ? (
          <Empty description="暂无帖子" />
        ) : (
          <List
            dataSource={posts}
            renderItem={(p) => (
              <List.Item
                key={p.id}
                onClick={() => router.push(`/dashboard/community/${p.id}`)}
                style={{ cursor: 'pointer' }}
                actions={[
                  <Space size={4} key="views">
                    <EyeOutlined /> {p.view_count}
                  </Space>,
                  <Space size={4} key="likes">
                    <LikeOutlined /> {p.like_count}
                  </Space>,
                  <Space size={4} key="cmts">
                    <MessageOutlined /> {p.comment_count}
                  </Space>,
                ]}
              >
                <List.Item.Meta
                  title={
                    <Space>
                      {p.pinned && (
                        <PushpinFilled style={{ color: '#faad14' }} />
                      )}
                      <span>{p.title}</span>
                      {p.moderation_status !== 'approved' && (
                        <Tag color={STATUS_TAG[p.moderation_status].color}>
                          {STATUS_TAG[p.moderation_status].label}
                        </Tag>
                      )}
                      {(p.tags ?? []).map((t) => (
                        <Tag key={t}>#{t}</Tag>
                      ))}
                    </Space>
                  }
                  description={
                    <Paragraph
                      ellipsis={{ rows: 2 }}
                      style={{ marginBottom: 0 }}
                    >
                      {p.body}
                    </Paragraph>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Card>

      <Drawer
        title="发布新帖"
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={520}
        extra={
          <Button
            type="primary"
            loading={submitting}
            onClick={handleCreate}
          >
            发布
          </Button>
        }
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="title"
            label="标题"
            rules={[{ required: true, min: 1, max: 255 }]}
          >
            <Input placeholder="简短概括你的话题" maxLength={255} showCount />
          </Form.Item>
          <Form.Item
            name="body"
            label="正文"
            rules={[{ required: true, min: 1 }]}
          >
            <Input.TextArea
              rows={12}
              placeholder="欢迎详细描述背景、观察和结论 (最多 20000 字)"
              maxLength={20000}
              showCount
            />
          </Form.Item>
          <Form.Item
            name="tags"
            label="标签"
            help="用逗号分隔多个标签，如: mission, compliance"
          >
            <Input placeholder="mission, review" />
          </Form.Item>
        </Form>
      </Drawer>
    </div>
  );
}
