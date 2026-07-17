/**
 * F3.2 · Trending posts leaderboard.
 * URL: /dashboard/community/trending
 */
'use client';
import {
  Alert, Button, Card, Empty, List, Radio, Segmented, Space, Tag,
  Typography, message,
} from 'antd';
import Link from 'next/link';
import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  ageDescription, getTrending, heatTierForPost, TrendingPost,
  trendingByTag,
} from '@/lib/community_likes';

const { Text, Title } = Typography;

const WINDOW_OPTIONS = [
  { label: '6h', value: 6 },
  { label: '1天', value: 24 },
  { label: '3天', value: 72 },
  { label: '7天', value: 168 },
];

export default function TrendingPage() {
  const [posts, setPosts] = useState<TrendingPost[]>([]);
  const [loading, setLoading] = useState(false);
  const [window_, setWindow] = useState(72);
  const [tenantScope, setTenantScope] = useState<'all' | 'org'>('all');
  const [view, setView] = useState<'list' | 'by-tag'>('list');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await getTrending({
        within_hours: window_, limit: 50,
        tenant_scope: tenantScope === 'org',
      });
      setPosts(rows);
    } catch (e: any) {
      message.error(`加载失败: ${e?.message ?? e}`);
    } finally {
      setLoading(false);
    }
  }, [window_, tenantScope]);

  useEffect(() => { void load(); }, [load]);

  const buckets = useMemo(() => trendingByTag(posts), [posts]);

  return (
    <div style={{ padding: 16 }}>
      <Title level={4}>🔥 热度榜</Title>

      <Card size="small" style={{ marginBottom: 12 }}>
        <Space wrap>
          <Text>时间窗口:</Text>
          <Radio.Group
            optionType="button" size="small"
            options={WINDOW_OPTIONS}
            value={window_}
            onChange={(e) => setWindow(e.target.value as number)}
          />
          <Text>范围:</Text>
          <Segmented
            size="small"
            value={tenantScope}
            onChange={(v) => setTenantScope(v as any)}
            options={[
              { label: '全站', value: 'all' },
              { label: '本组织', value: 'org' },
            ]}
          />
          <Text>视图:</Text>
          <Segmented
            size="small"
            value={view}
            onChange={(v) => setView(v as any)}
            options={[
              { label: '排行榜', value: 'list' },
              { label: '按标签', value: 'by-tag' },
            ]}
          />
          <Button onClick={() => void load()} loading={loading}>
            刷新
          </Button>
          <Text type="secondary">
            共 {posts.length} 条 · 按 hot_score = 加权互动 × 时间衰减
            (半衰期 24h)
          </Text>
        </Space>
      </Card>

      {posts.length === 0 && !loading ? (
        <Empty description="该时间窗口内没有热门帖子" />
      ) : view === 'list' ? (
        <TrendingList posts={posts} loading={loading} />
      ) : (
        <ByTagView buckets={buckets} />
      )}
    </div>
  );
}

function TrendingList(props: {
  posts: TrendingPost[]; loading: boolean;
}) {
  return (
    <Card size="small">
      <List<TrendingPost>
        dataSource={props.posts}
        loading={props.loading}
        renderItem={(p, i) => {
          const tier = heatTierForPost(p);
          return (
            <List.Item
              actions={[
                <Link key="view"
                  href={`/dashboard/community/${p.post_id}`}>
                  <Button size="small" type="link">查看</Button>
                </Link>,
              ]}
            >
              <List.Item.Meta
                avatar={
                  <div style={{
                    width: 36, height: 36,
                    borderRadius: 4,
                    background: '#f5f5f5',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontWeight: 700,
                    color: '#595959',
                  }}>
                    #{i + 1}
                  </div>
                }
                title={
                  <Space>
                    <Text strong>{p.title}</Text>
                    <Tag color={tier.color}>{tier.label}</Tag>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      score {p.hot_score.toFixed(2)}
                    </Text>
                  </Space>
                }
                description={
                  <Space size={4} wrap>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {ageDescription(p.age_hours)}
                    </Text>
                    {(p.tags ?? []).slice(0, 4).map((t) => (
                      <Tag key={t} color="geekblue">{t}</Tag>
                    ))}
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      👁 {p.view_count} · 👍 {p.like_count} · 💬{' '}
                      {p.comment_count}
                    </Text>
                  </Space>
                }
              />
            </List.Item>
          );
        }}
      />
    </Card>
  );
}

function ByTagView(props: {
  buckets: Array<{
    tag: string; posts: TrendingPost[]; total_score: number;
  }>;
}) {
  if (props.buckets.length === 0) {
    return <Alert type="info" showIcon message="所有帖子都无标签" />;
  }
  return (
    <Space direction="vertical" size="middle"
      style={{ width: '100%' }}>
      {props.buckets.map((b) => (
        <Card key={b.tag} size="small"
          title={
            <Space>
              <Tag color="blue">{b.tag}</Tag>
              <Text type="secondary" style={{ fontSize: 12 }}>
                总 score {b.total_score.toFixed(2)} ·
                {b.posts.length} 条
              </Text>
            </Space>
          }
        >
          <List<TrendingPost>
            size="small"
            dataSource={b.posts.slice(0, 5)}
            renderItem={(p) => (
              <List.Item
                actions={[
                  <Link key="v"
                    href={`/dashboard/community/${p.post_id}`}>
                    <Button size="small" type="link">
                      查看
                    </Button>
                  </Link>,
                ]}
              >
                <Text>{p.title}</Text>
                <Text type="secondary"
                  style={{ marginLeft: 8, fontSize: 12 }}>
                  {ageDescription(p.age_hours)} · 👍 {p.like_count} ·
                  💬 {p.comment_count}
                </Text>
              </List.Item>
            )}
          />
        </Card>
      ))}
    </Space>
  );
}
