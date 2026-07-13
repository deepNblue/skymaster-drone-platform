'use client';

/**
 * Community Reports Moderation — T6.5.
 * Admin queue for user-submitted reports against posts.
 * Path: /dashboard/community/moderation/reports
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
  Empty,
  Result,
  Spin,
} from 'antd';
import {
  ArrowLeftOutlined,
  FlagOutlined,
  CheckOutlined,
  StopOutlined,
} from '@ant-design/icons';
import Link from 'next/link';
import {
  listOpenReports,
  resolveReport,
  ReportOut,
  REPORT_REASONS,
} from '@/lib/community';
import { getMe } from '@/lib/api';

const { Title, Text, Paragraph } = Typography;

const REASON_LABEL = Object.fromEntries(
  REPORT_REASONS.map((r) => [r.value, r.label]),
) as Record<string, string>;

export default function CommunityReportModerationPage() {
  const router = useRouter();
  const [items, setItems] = useState<ReportOut[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);

  // resolve/dismiss note modal
  const [target, setTarget] = useState<ReportOut | null>(null);
  const [action, setAction] = useState<'resolve' | 'dismiss'>('resolve');
  const [note, setNote] = useState('');

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listOpenReports();
      setItems(res.items);
      setTotal(res.total);
    } catch (e: any) {
      const st = e?.response?.status;
      if (st === 403) {
        setForbidden(true);
      } else {
        message.error(`加载失败: ${e?.response?.data?.detail ?? e.message}`);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const me = await getMe();
        if (me?.role !== 'admin') {
          setForbidden(true);
          setLoading(false);
          return;
        }
      } catch {
        setForbidden(true);
        setLoading(false);
        return;
      }
      reload();
    })();
  }, [reload]);

  const submit = async () => {
    if (!target) return;
    try {
      await resolveReport(target.id, action, note || undefined);
      message.success(action === 'resolve' ? '已标记为处理' : '已忽略举报');
      setTarget(null);
      setNote('');
      reload();
    } catch (e: any) {
      message.error(`操作失败: ${e?.response?.data?.detail ?? e.message}`);
    }
  };

  if (forbidden) {
    return (
      <Result
        status="403"
        title="仅管理员可访问"
        subTitle="该页面用于审核用户举报，需 admin 角色。"
        extra={
          <Button onClick={() => router.push('/dashboard/community')}>
            返回社区
          </Button>
        }
      />
    );
  }

  return (
    <div style={{ padding: 16 }}>
      <Space
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          marginBottom: 12,
        }}
      >
        <Space>
          <Button
            type="link"
            icon={<ArrowLeftOutlined />}
            style={{ paddingLeft: 0 }}
            onClick={() => router.push('/dashboard/community/moderation')}
          >
            返回帖子审核
          </Button>
          <Title level={4} style={{ margin: 0 }}>
            <FlagOutlined /> 举报处理
          </Title>
          <Tag>{total} 待处理</Tag>
        </Space>
        <Button onClick={reload}>刷新</Button>
      </Space>

      <Card size="small">
        {loading ? (
          <div style={{ textAlign: 'center', padding: 40 }}>
            <Spin />
          </div>
        ) : items.length === 0 ? (
          <Empty description="举报队列为空 🎉" />
        ) : (
          <List
            dataSource={items}
            renderItem={(r) => (
              <List.Item
                key={r.id}
                actions={[
                  <Button
                    key="resolve"
                    icon={<CheckOutlined />}
                    onClick={() => {
                      setTarget(r);
                      setAction('resolve');
                    }}
                  >
                    处理
                  </Button>,
                  <Button
                    key="dismiss"
                    icon={<StopOutlined />}
                    onClick={() => {
                      setTarget(r);
                      setAction('dismiss');
                    }}
                  >
                    忽略
                  </Button>,
                ]}
              >
                <List.Item.Meta
                  avatar={<FlagOutlined style={{ fontSize: 20, color: '#faad14' }} />}
                  title={
                    <Space>
                      <Tag color="warning">
                        {REASON_LABEL[r.reason] ?? r.reason}
                      </Tag>
                      <Link
                        href={`/dashboard/community/${r.post_id}`}
                        target="_blank"
                      >
                        <Text underline>查看被举报帖子</Text>
                      </Link>
                    </Space>
                  }
                  description={
                    <Space direction="vertical" size={2}>
                      {r.note && (
                        <Paragraph
                          type="secondary"
                          style={{
                            fontSize: 12,
                            marginBottom: 0,
                            whiteSpace: 'pre-wrap',
                          }}
                        >
                          {r.note}
                        </Paragraph>
                      )}
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        举报人: {r.reporter_id?.slice(0, 8) ?? '匿名'} ·{' '}
                        {new Date(r.created_at).toLocaleString('zh-CN')}
                      </Text>
                    </Space>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Card>

      <Modal
        open={!!target}
        title={action === 'resolve' ? '标记为已处理' : '忽略此举报'}
        okText="提交"
        onOk={submit}
        onCancel={() => {
          setTarget(null);
          setNote('');
        }}
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {action === 'resolve'
              ? '记录你如何处理（例如：已归档帖子、已警告作者），可选。'
              : '记录忽略原因（例如：查证无违规），可选。'}
          </Text>
          <Input.TextArea
            rows={3}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="备注..."
            maxLength={1000}
            showCount
          />
        </Space>
      </Modal>
    </div>
  );
}
