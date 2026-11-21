/**
 * F3.4 · Notification inbox.
 * URL: /dashboard/community/notifications
 */
'use client';
import {
  Badge, Button, Card, Divider, Empty, List, Segmented, Space, Tag,
  Typography, message,
} from 'antd';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import Link from 'next/link';
import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  Notification, NotificationKind, UnreadSummary, describe, groupByDay,
  getUnreadSummary, iconFor, labelFor, listNotifications, markAllRead,
  markRead,
} from '@/lib/community_notifications';

dayjs.extend(relativeTime);

const { Text, Title } = Typography;
const KIND_OPTIONS: Array<{
  label: string; value: 'all' | NotificationKind;
}> = [
  { label: '全部', value: 'all' },
  { label: '👥 新粉丝', value: 'new_follower' },
  { label: '👍 点赞', value: 'post_liked' },
  { label: '💬 回复', value: 'post_reply' },
  { label: '📣 提及', value: 'mention' },
];

export default function InboxPage() {
  const [items, setItems] = useState<Notification[]>([]);
  const [summary, setSummary] = useState<UnreadSummary>({
    new_follower: 0, post_liked: 0, post_reply: 0, mention: 0,
    total: 0,
  });
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] =
    useState<'all' | NotificationKind>('all');
  const [showUnreadOnly, setShowUnreadOnly] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const kinds: NotificationKind[] | undefined =
        filter === 'all' ? undefined : [filter];
      const [rows, s] = await Promise.all([
        listNotifications({
          only_unread: showUnreadOnly,
          kinds, limit: 100,
        }),
        getUnreadSummary(),
      ]);
      setItems(rows);
      setSummary(s);
    } catch (e: any) {
      message.error(`加载失败: ${e?.message ?? e}`);
    } finally {
      setLoading(false);
    }
  }, [filter, showUnreadOnly]);

  useEffect(() => { void load(); }, [load]);

  const doMarkOne = useCallback(async (id: string) => {
    try {
      await markRead(id);
      setItems((prev) => prev.map(
        (n) => n.id === id ? {
          ...n, read: true, read_at: new Date().toISOString(),
        } : n,
      ));
      setSummary((s) => ({
        ...s, total: Math.max(0, s.total - 1),
      }));
    } catch (e: any) {
      message.error(`失败: ${e?.message ?? e}`);
    }
  }, []);

  const doMarkAll = useCallback(async (
    kind?: NotificationKind,
  ) => {
    try {
      const r = await markAllRead(kind ? [kind] : undefined);
      message.success(`已标记 ${r.updated} 条为已读`);
      await load();
    } catch (e: any) {
      message.error(`失败: ${e?.message ?? e}`);
    }
  }, [load]);

  const grouped = useMemo(() => groupByDay(items), [items]);

  return (
    <div style={{ padding: 16 }}>
      <Space
        align="baseline"
        style={{
          width: '100%', justifyContent: 'space-between',
          marginBottom: 12,
        }}>
        <Title level={4} style={{ margin: 0 }}>
          🔔 通知中心
          {summary.total > 0 && (
            <Badge
              count={summary.total}
              style={{ marginLeft: 8 }}
            />
          )}
        </Title>
        <Button
          onClick={() => void doMarkAll()}
          disabled={summary.total === 0}
        >
          全部标为已读
        </Button>
      </Space>

      <Card size="small" style={{ marginBottom: 12 }}>
        <Space wrap size="middle">
          <Space size="small">
            {KIND_OPTIONS.map((opt) => (
              <KindChip
                key={opt.value}
                label={opt.label}
                active={filter === opt.value}
                count={opt.value === 'all'
                  ? summary.total
                  : (summary[opt.value] ?? 0)}
                onClick={() => setFilter(opt.value)}
              />
            ))}
          </Space>
          <Divider type="vertical" />
          <Segmented
            size="small"
            value={showUnreadOnly ? 'unread' : 'all'}
            onChange={(v) => setShowUnreadOnly(v === 'unread')}
            options={[
              { label: '全部', value: 'all' },
              { label: '仅未读', value: 'unread' },
            ]}
          />
          {filter !== 'all' && (
            <Button
              size="small" type="link"
              onClick={() => void doMarkAll(
                filter as NotificationKind,
              )}
              disabled={(summary[filter] ?? 0) === 0}
            >
              该分类全部已读
            </Button>
          )}
        </Space>
      </Card>

      {items.length === 0 && !loading ? (
        <Empty description="没有通知" />
      ) : (
        <Space direction="vertical" size="middle"
          style={{ width: '100%' }}>
          {grouped.map((g) => (
            <Card key={g.day} size="small" title={g.day}>
              <List<Notification>
                loading={loading}
                dataSource={g.items}
                renderItem={(n) => (
                  <List.Item
                    style={{
                      background: n.read
                        ? 'transparent' : '#f0f7ff',
                      padding: '8px 12px',
                    }}
                    actions={[
                      n.post_id && (
                        <Link key="v"
                          href={`/dashboard/community/${n.post_id}`}>
                          <Button size="small" type="link">
                            查看
                          </Button>
                        </Link>
                      ),
                      !n.read && (
                        <Button
                          key="r" size="small" type="link"
                          onClick={() => void doMarkOne(n.id)}
                        >
                          标为已读
                        </Button>
                      ),
                    ].filter(Boolean) as React.ReactNode[]}
                  >
                    <List.Item.Meta
                      avatar={
                        <div style={{
                          fontSize: 22, width: 32,
                          textAlign: 'center',
                        }}>
                          {iconFor(n.kind)}
                        </div>
                      }
                      title={
                        <Space size={4}>
                          <Text strong={!n.read}>
                            {describe(n)}
                          </Text>
                          {!n.read && (
                            <Tag color="blue">新</Tag>
                          )}
                        </Space>
                      }
                      description={
                        <Text type="secondary"
                          style={{ fontSize: 12 }}>
                          {labelFor(n.kind)} ·{' '}
                          {n.created_at
                            ? dayjs(n.created_at).fromNow()
                            : ''}
                        </Text>
                      }
                    />
                  </List.Item>
                )}
              />
            </Card>
          ))}
        </Space>
      )}
    </div>
  );
}

function KindChip(props: {
  label: string;
  active: boolean;
  count: number;
  onClick: () => void;
}) {
  return (
    <Button
      size="small"
      type={props.active ? 'primary' : 'default'}
      onClick={props.onClick}
    >
      {props.label}
      {props.count > 0 && (
        <Badge
          count={props.count}
          size="small"
          style={{ marginLeft: 4 }}
        />
      )}
    </Button>
  );
}
