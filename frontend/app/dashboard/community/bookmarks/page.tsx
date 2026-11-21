/**
 * F3.1 · My Bookmarks page.
 * URL: /dashboard/community/bookmarks
 */
'use client';
import {
  Alert, Button, Card, Empty, Input, List, Space, Tag, Typography,
  message,
} from 'antd';
import dayjs from 'dayjs';
import Link from 'next/link';
import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  Bookmark, bookmarkTagCounts, listBookmarks, removeBookmark,
} from '@/lib/community_bookmarks';

const { Text, Title } = Typography;

export default function BookmarksPage() {
  const [items, setItems] = useState<Bookmark[]>([]);
  const [loading, setLoading] = useState(false);
  const [q, setQ] = useState('');
  const [selectedTag, setSelectedTag] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await listBookmarks({ limit: 100 }));
    } catch (e: any) {
      message.error(`加载失败: ${e?.message ?? e}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const doRemove = useCallback(async (b: Bookmark) => {
    try {
      await removeBookmark(b.post_id);
      setItems((prev) => prev.filter((x) => x.post_id !== b.post_id));
      message.success('已取消收藏');
    } catch (e: any) {
      message.error(`失败: ${e?.message ?? e}`);
    }
  }, []);

  const tags = useMemo(() => bookmarkTagCounts(items), [items]);
  const filtered = useMemo(() => {
    const qq = q.trim().toLowerCase();
    return items.filter((b) => {
      if (selectedTag && !b.tags?.includes(selectedTag)) return false;
      if (!qq) return true;
      return (
        b.title.toLowerCase().includes(qq) ||
        (b.tags ?? []).some((t) => t.toLowerCase().includes(qq))
      );
    });
  }, [items, q, selectedTag]);

  return (
    <div style={{ padding: 16 }}>
      <Title level={4}>⭐ 我的收藏</Title>

      <Card size="small" style={{ marginBottom: 12 }}>
        <Space wrap>
          <Input.Search
            placeholder="搜索标题或标签"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            style={{ width: 240 }}
            allowClear
          />
          <Button onClick={() => void load()} loading={loading}>
            刷新
          </Button>
          <Text type="secondary">
            共 {items.length} 条收藏 · 显示 {filtered.length}
          </Text>
        </Space>
      </Card>

      {tags.length > 0 && (
        <Card size="small" style={{ marginBottom: 12 }} title="🏷️ 标签">
          <Space wrap>
            {selectedTag && (
              <Tag closable
                color="blue"
                onClose={() => setSelectedTag(null)}>
                筛选: {selectedTag}
              </Tag>
            )}
            {tags.map((t) => (
              <Tag key={t.tag}
                style={{ cursor: 'pointer' }}
                color={selectedTag === t.tag ? 'blue' : 'default'}
                onClick={() =>
                  setSelectedTag(
                    selectedTag === t.tag ? null : t.tag,
                  )
                }>
                {t.tag} ({t.count})
              </Tag>
            ))}
          </Space>
        </Card>
      )}

      {items.length === 0 && !loading ? (
        <Empty description="尚未收藏任何帖子">
          <Link href="/dashboard/community">
            <Button type="primary">去逛社区</Button>
          </Link>
        </Empty>
      ) : filtered.length === 0 ? (
        <Alert type="info" showIcon
          message="没有符合条件的收藏" />
      ) : (
        <List<Bookmark>
          dataSource={filtered}
          loading={loading}
          renderItem={(b) => (
            <List.Item
              actions={[
                <Link href={`/dashboard/community/${b.post_id}`}
                  key="view">
                  <Button size="small" type="link">查看</Button>
                </Link>,
                <Button size="small" type="link" danger key="remove"
                  onClick={() => void doRemove(b)}>
                  取消收藏
                </Button>,
              ]}
            >
              <List.Item.Meta
                title={<Text strong>{b.title}</Text>}
                description={
                  <Space size={4} wrap>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      收藏于 {dayjs(b.bookmarked_at)
                        .format('YYYY-MM-DD HH:mm')}
                    </Text>
                    {(b.tags ?? []).map((t) => (
                      <Tag key={t} color="geekblue">{t}</Tag>
                    ))}
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      👁 {b.view_count} · 👍 {b.like_count} · 💬{' '}
                      {b.comment_count}
                    </Text>
                  </Space>
                }
              />
            </List.Item>
          )}
        />
      )}
    </div>
  );
}
