/**
 * F3.3 · Following feed + my follows page.
 * URL: /dashboard/community/following
 */
'use client';
import {
  Alert, Avatar, Badge, Button, Card, Empty, List, Radio, Segmented,
  Space, Statistic, Tabs, Tag, Typography, message,
} from 'antd';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import Link from 'next/link';
import { useCallback, useEffect, useMemo, useState } from 'react';

dayjs.extend(relativeTime);

import {
  FeedPost, FollowUser, feedByAuthor, getFollowFeed,
  getMyFollowCounts, listMyFollowers, listMyFollowing,
  mutualFollows, suggestedToFollowBack, unfollowUser,
} from '@/lib/community_follows';

const { Text, Title } = Typography;

const WINDOW_OPTIONS = [
  { label: '1天', value: 24 },
  { label: '3天', value: 72 },
  { label: '7天', value: 168 },
  { label: '30天', value: 720 },
];

export default function FollowingPage() {
  const [counts, setCounts] = useState({ following: 0, followers: 0 });
  const [followingList, setFollowingList] =
    useState<FollowUser[]>([]);
  const [followerList, setFollowerList] = useState<FollowUser[]>([]);
  const [feed, setFeed] = useState<FeedPost[]>([]);
  const [loading, setLoading] = useState(false);
  const [window_, setWindow] = useState(168);
  const [feedView, setFeedView] = useState<'flat' | 'by-author'>('flat');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [c, following, followers, f] = await Promise.all([
        getMyFollowCounts(),
        listMyFollowing({ limit: 500 }),
        listMyFollowers({ limit: 500 }),
        getFollowFeed({ within_hours: window_, limit: 100 }),
      ]);
      setCounts(c);
      setFollowingList(following);
      setFollowerList(followers);
      setFeed(f);
    } catch (e: any) {
      message.error(`加载失败: ${e?.message ?? e}`);
    } finally {
      setLoading(false);
    }
  }, [window_]);

  useEffect(() => { void load(); }, [load]);

  const mutual = useMemo(
    () => mutualFollows(followingList, followerList),
    [followingList, followerList],
  );
  const suggestions = useMemo(
    () => suggestedToFollowBack(followingList, followerList),
    [followingList, followerList],
  );
  const feedGroups = useMemo(() => feedByAuthor(feed), [feed]);

  const doUnfollow = useCallback(async (uid: string) => {
    try {
      await unfollowUser(uid);
      setFollowingList((prev) =>
        prev.filter((u) => u.user_id !== uid),
      );
      setCounts((c) => ({
        ...c, following: Math.max(0, c.following - 1),
      }));
      message.success('已取消关注');
    } catch (e: any) {
      message.error(`失败: ${e?.message ?? e}`);
    }
  }, []);

  return (
    <div style={{ padding: 16 }}>
      <Title level={4}>👥 关注 / 粉丝</Title>

      <Space size="large" style={{ marginBottom: 12 }}>
        <Statistic title="关注中" value={counts.following} />
        <Statistic title="粉丝" value={counts.followers} />
        <Statistic title="互关" value={mutual.size} />
      </Space>

      <Tabs
        defaultActiveKey="feed"
        items={[
          {
            key: 'feed',
            label: '📰 关注动态',
            children: (
              <FeedTab
                feed={feed}
                groups={feedGroups}
                loading={loading}
                window_={window_}
                setWindow={setWindow}
                view={feedView}
                setView={setFeedView}
              />
            ),
          },
          {
            key: 'following',
            label: `关注中 (${counts.following})`,
            children: (
              <UserListTab
                users={followingList}
                mutual={mutual}
                showAction="unfollow"
                onAction={doUnfollow}
                emptyText="你还没关注任何人"
              />
            ),
          },
          {
            key: 'followers',
            label: `粉丝 (${counts.followers})`,
            children: (
              <>
                {suggestions.length > 0 && (
                  <Alert
                    type="info" showIcon
                    style={{ marginBottom: 12 }}
                    message={`有 ${suggestions.length}
                      位关注了你但你还没回关`}
                  />
                )}
                <UserListTab
                  users={followerList}
                  mutual={mutual}
                  showAction="none"
                  onAction={() => {}}
                  emptyText="还没有粉丝"
                />
              </>
            ),
          },
        ]}
      />
    </div>
  );
}

function FeedTab(props: {
  feed: FeedPost[];
  groups: Array<{
    author_id: string; author_email: string;
    posts: FeedPost[];
  }>;
  loading: boolean;
  window_: number;
  setWindow: (n: number) => void;
  view: 'flat' | 'by-author';
  setView: (v: 'flat' | 'by-author') => void;
}) {
  return (
    <>
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space wrap>
          <Text>时间窗口:</Text>
          <Radio.Group
            optionType="button" size="small"
            options={WINDOW_OPTIONS}
            value={props.window_}
            onChange={(e) =>
              props.setWindow(e.target.value as number)
            }
          />
          <Text>视图:</Text>
          <Segmented
            size="small"
            value={props.view}
            onChange={(v) => props.setView(v as any)}
            options={[
              { label: '时间流', value: 'flat' },
              { label: '按作者', value: 'by-author' },
            ]}
          />
          <Text type="secondary">
            共 {props.feed.length} 条动态
          </Text>
        </Space>
      </Card>
      {props.feed.length === 0 ? (
        <Empty description="所关注用户在此窗口内没有新帖" />
      ) : props.view === 'flat' ? (
        <List<FeedPost>
          loading={props.loading}
          dataSource={props.feed}
          renderItem={(p) => (
            <List.Item
              actions={[
                <Link key="v"
                  href={`/dashboard/community/${p.post_id}`}>
                  <Button size="small" type="link">查看</Button>
                </Link>,
              ]}
            >
              <List.Item.Meta
                avatar={
                  <Avatar>{
                    (p.author_email ?? '?').slice(0, 1).toUpperCase()
                  }</Avatar>
                }
                title={<Text strong>{p.title}</Text>}
                description={
                  <Space size={4} wrap>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {p.author_email} ·{' '}
                      {p.created_at
                        ? dayjs(p.created_at).fromNow()
                        : ''}
                    </Text>
                    {(p.tags ?? []).map((t) => (
                      <Tag key={t} color="geekblue">{t}</Tag>
                    ))}
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      👍 {p.like_count} · 💬 {p.comment_count}
                    </Text>
                  </Space>
                }
              />
            </List.Item>
          )}
        />
      ) : (
        <Space direction="vertical" size="middle"
          style={{ width: '100%' }}>
          {props.groups.map((g) => (
            <Card key={g.author_id} size="small"
              title={
                <Space>
                  <Avatar size="small">
                    {g.author_email.slice(0, 1).toUpperCase()}
                  </Avatar>
                  <Text strong>{g.author_email}</Text>
                  <Badge count={g.posts.length}
                    style={{ backgroundColor: '#1677ff' }} />
                </Space>
              }
            >
              <List<FeedPost>
                size="small"
                dataSource={g.posts.slice(0, 5)}
                renderItem={(p) => (
                  <List.Item
                    actions={[
                      <Link key="v"
                        href={`/dashboard/community/${p.post_id}`}>
                        <Button size="small" type="link">查看</Button>
                      </Link>,
                    ]}
                  >
                    <Text>{p.title}</Text>
                    <Text type="secondary"
                      style={{ marginLeft: 8, fontSize: 12 }}>
                      {p.created_at
                        ? dayjs(p.created_at).fromNow()
                        : ''} · 👍 {p.like_count}
                    </Text>
                  </List.Item>
                )}
              />
            </Card>
          ))}
        </Space>
      )}
    </>
  );
}

function UserListTab(props: {
  users: FollowUser[];
  mutual: Set<string>;
  showAction: 'unfollow' | 'none';
  onAction: (uid: string) => void;
  emptyText: string;
}) {
  if (props.users.length === 0) {
    return <Empty description={props.emptyText} />;
  }
  return (
    <List<FollowUser>
      dataSource={props.users}
      renderItem={(u) => (
        <List.Item
          actions={
            props.showAction === 'unfollow'
              ? [
                <Button
                  key="unfollow" size="small" danger
                  onClick={() => props.onAction(u.user_id)}
                >
                  取消关注
                </Button>,
              ]
              : []
          }
        >
          <List.Item.Meta
            avatar={
              <Avatar>{u.email.slice(0, 1).toUpperCase()}</Avatar>
            }
            title={
              <Space>
                <Text strong>{u.email}</Text>
                <Tag color="default">{u.role}</Tag>
                {props.mutual.has(u.user_id) && (
                  <Tag color="green">互相关注</Tag>
                )}
              </Space>
            }
            description={
              <Text type="secondary" style={{ fontSize: 12 }}>
                自 {dayjs(u.followed_at).format('YYYY-MM-DD')}
              </Text>
            }
          />
        </List.Item>
      )}
    />
  );
}
