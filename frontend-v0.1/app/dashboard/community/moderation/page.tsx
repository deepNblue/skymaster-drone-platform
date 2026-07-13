'use client';

/**
 * Community moderation queue — admin only.
 * Path: /dashboard/community/moderation
 *
 * Shows all pending posts with quick approve / reject / archive
 * actions. Each row expands to reveal the full body + any
 * moderation reason attached by the automated keyword scan.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Card,
  List,
  Space,
  Tag,
  Typography,
  Button,
  Modal,
  Input,
  message,
  Spin,
  Empty,
  Alert,
  Result,
} from 'antd';
import {
  ArrowLeftOutlined,
  SafetyOutlined,
  CheckOutlined,
  CloseOutlined,
  InboxOutlined,
  FlagOutlined,
} from '@ant-design/icons';
import {
  fetchModerationQueue,
  moderateCommunityPost,
  CommunityPost,
} from '@/lib/community';
import { getMe } from '@/lib/api';

const { Title, Text, Paragraph } = Typography;

export default function CommunityModerationPage() {
  const router = useRouter();
  const [posts, setPosts] = useState<CommunityPost[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);

  // reject-with-reason modal
  const [rejectTarget, setRejectTarget] = useState<CommunityPost | null>(null);
  const [rejectReason, setRejectReason] = useState('');

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchModerationQueue({ limit: 100 });
      setPosts(res.items);
      setTotal(res.total);
    } catch (e: any) {
      const st = e?.response?.status;
      if (st === 403) {
        setForbidden(true);
      } else {
        message.error(
          `加载失败: ${e?.response?.data?.detail ?? e.message}`,
        );
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    getMe()
      .then((u: any) => {
        if (u?.role !== 'admin') {
          setForbidden(true);
          setLoading(false);
        } else {
          reload();
        }
      })
      .catch(() => {
        setForbidden(true);
        setLoading(false);
      });
  }, [reload]);

  const act = async (
    p: CommunityPost,
    action: 'approve' | 'reject' | 'archive',
    reason?: string,
  ) => {
    try {
      await moderateCommunityPost(p.id, action, reason);
      message.success(
        `${action === 'approve' ? '已通过' : action === 'reject' ? '已拒绝' : '已归档'}: ${p.title}`,
      );
      reload();
    } catch (e: any) {
      message.error(
        `操作失败: ${e?.response?.data?.detail ?? e.message}`,
      );
    }
  };

  if (forbidden) {
    return (
      <Result
        status="403"
        title="403"
        subTitle="审核队列仅对管理员开放。"
        extra={
          <Button
            type="primary"
            onClick={() => router.push('/dashboard/community')}
          >
            返回社区
          </Button>
        }
      />
    );
  }

  return (
    <div style={{ padding: 16 }}>
      <Button
        type="link"
        icon={<ArrowLeftOutlined />}
        style={{ paddingLeft: 0, marginBottom: 8 }}
        onClick={() => router.push('/dashboard/community')}
      >
        返回社区
      </Button>
      <Button
        type="link"
        icon={<FlagOutlined />}
        style={{ marginBottom: 8, marginLeft: 8 }}
        onClick={() => router.push('/dashboard/community/moderation/reports')}
      >
        用户举报队列
      </Button>

      <div style={{ marginBottom: 12 }}>
        <Title level={4} style={{ margin: 0 }}>
          <SafetyOutlined /> 社区审核队列
        </Title>
        <Text type="secondary">
          待审 <Text strong>{total}</Text> 条内容。审核建议：命中营销/敏感词但整体合规可通过；违规内容直接拒绝并记录理由。
        </Text>
      </div>

      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 12 }}
        message="审核准则"
        description="1) 涉军/暴恐/毒品/黄/违法 → 一律拒绝；2) 广告/私聊出售/非本平台业务 → 可归档；3) 有价值但有小瑕疵 → 提示后通过。"
      />

      <Card size="small">
        {loading ? (
          <div style={{ textAlign: 'center', padding: 40 }}>
            <Spin />
          </div>
        ) : posts.length === 0 ? (
          <Empty description="队列为空，做得漂亮" />
        ) : (
          <List
            dataSource={posts}
            renderItem={(p) => (
              <List.Item
                key={p.id}
                actions={[
                  <Button
                    key="approve"
                    size="small"
                    type="primary"
                    icon={<CheckOutlined />}
                    onClick={() => act(p, 'approve')}
                  >
                    通过
                  </Button>,
                  <Button
                    key="reject"
                    size="small"
                    danger
                    icon={<CloseOutlined />}
                    onClick={() => {
                      setRejectTarget(p);
                      setRejectReason('');
                    }}
                  >
                    拒绝
                  </Button>,
                  <Button
                    key="archive"
                    size="small"
                    icon={<InboxOutlined />}
                    onClick={() => act(p, 'archive')}
                  >
                    归档
                  </Button>,
                ]}
              >
                <List.Item.Meta
                  title={
                    <Space>
                      <span>{p.title}</span>
                      <Tag color="processing">待审</Tag>
                      {(p.tags ?? []).map((t) => (
                        <Tag key={t}>#{t}</Tag>
                      ))}
                    </Space>
                  }
                  description={
                    <>
                      {p.moderation_reason && (
                        <div style={{ marginBottom: 4 }}>
                          <Text type="warning" style={{ fontSize: 12 }}>
                            自动扫描: {p.moderation_reason}
                          </Text>
                        </div>
                      )}
                      <Paragraph
                        ellipsis={{ rows: 3, expandable: true, symbol: '展开' }}
                        style={{ marginBottom: 0, fontSize: 12 }}
                      >
                        {p.body}
                      </Paragraph>
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        作者: {p.author_id?.slice(0, 8) ?? '匿名'} ·{' '}
                        {new Date(p.created_at).toLocaleString('zh-CN')}
                      </Text>
                    </>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Card>

      <Modal
        open={!!rejectTarget}
        title={`拒绝: ${rejectTarget?.title ?? ''}`}
        okText="确认拒绝"
        okType="danger"
        cancelText="取消"
        onOk={async () => {
          if (!rejectTarget) return;
          await act(rejectTarget, 'reject', rejectReason || undefined);
          setRejectTarget(null);
        }}
        onCancel={() => setRejectTarget(null)}
      >
        <Text type="secondary" style={{ fontSize: 12 }}>
          填写理由以便作者知情（可留空使用默认）
        </Text>
        <Input.TextArea
          style={{ marginTop: 8 }}
          rows={3}
          value={rejectReason}
          onChange={(e) => setRejectReason(e.target.value)}
          placeholder="如: 内容与本平台无关 / 涉嫌违规 / …"
          maxLength={512}
        />
      </Modal>
    </div>
  );
}
