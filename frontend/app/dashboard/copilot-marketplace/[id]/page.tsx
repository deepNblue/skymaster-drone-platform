'use client';

/**
 * E2.6 · Workflow 市场 · Listing 详情 & 评分 & 安装.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import {
  Alert, Button, Card, Divider, Input, List, Modal, Rate, Space, Spin, Tag,
  Typography, message,
} from 'antd';
import {
  getListing, getMyRating, installListing, listRatings, rate,
  starEmoji, visibilityBadge,
  type ListingDetail, type Rating,
} from '@/lib/copilot_workflow_marketplace';

const { Title, Text, Paragraph } = Typography;

export default function ListingDetailPage(): React.ReactElement {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const id = params?.id ?? '';
  const [listing, setListing] = useState<ListingDetail | null>(null);
  const [ratings, setRatings] = useState<Rating[]>([]);
  const [myRating, setMyRating] = useState<Rating | null>(null);
  const [installing, setInstalling] = useState(false);
  const [rateModal, setRateModal] = useState(false);
  const [stars, setStars] = useState(4);
  const [comment, setComment] = useState('');

  const reload = useCallback(async () => {
    if (!id) return;
    try {
      const [ld, r, mine] = await Promise.all([
        getListing(id),
        listRatings(id),
        getMyRating(id),
      ]);
      setListing(ld);
      setRatings(r.items);
      setMyRating(mine);
      if (mine) {
        setStars(mine.stars);
        setComment(mine.comment ?? '');
      }
    } catch (e) {
      message.error(String(e));
    }
  }, [id]);

  useEffect(() => { reload(); }, [reload]);

  const doInstall = async () => {
    setInstalling(true);
    try {
      const r = await installListing(id, {});
      message.success(`已克隆到 workflow ${r.workflow_name}`);
      router.push(`/dashboard/copilot-workflows/${r.workflow_id}`);
    } catch (e) {
      message.error(String(e));
    } finally {
      setInstalling(false);
    }
  };

  const submitRating = async () => {
    try {
      await rate(id, { stars, comment: comment || undefined });
      message.success('评分已提交');
      setRateModal(false);
      reload();
    } catch (e) { message.error(String(e)); }
  };

  if (!listing) {
    return <div style={{ padding: 24 }}><Spin /> 加载中…</div>;
  }

  const vb = visibilityBadge(listing.visibility);

  return (
    <div style={{ padding: 24, maxWidth: 900, margin: '0 auto' }}>
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        <Title level={3}>
          {listing.title} <Tag color={vb.color}>{vb.text}</Tag>
        </Title>
        <Space wrap>
          {(listing.tags ?? []).map((t) => <Tag key={t}>{t}</Tag>)}
        </Space>
        <Paragraph type="secondary">{listing.summary || '（无描述）'}</Paragraph>

        <Space wrap>
          <Text>版本 v{listing.workflow_version}</Text>
          <Divider type="vertical" />
          <Text>安装 {listing.install_count} 次</Text>
          <Divider type="vertical" />
          <Text>{starEmoji(listing.avg_rating)} {listing.avg_rating.toFixed(1)} ({listing.rating_count})</Text>
        </Space>

        <Space>
          <Button
            type="primary" onClick={doInstall} loading={installing}
          >
            克隆到我的工作区
          </Button>
          <Button onClick={() => setRateModal(true)}>
            {myRating ? '修改我的评分' : '给个评分'}
          </Button>
        </Space>

        <Card title="DSL 快照 (只读)">
          <pre style={{
            background: '#f5f5f5', padding: 12, borderRadius: 4,
            overflow: 'auto', maxHeight: 400,
          }}>
            {listing.dsl_yaml_snapshot}
          </pre>
        </Card>

        <Card title={`评价 (${ratings.length})`}>
          {ratings.length === 0 ? (
            <Text type="secondary">还没有人评价，先来试试吧。</Text>
          ) : (
            <List
              dataSource={ratings}
              renderItem={(r) => (
                <List.Item>
                  <Space direction="vertical" style={{ width: '100%' }}>
                    <Space>
                      <Text>{starEmoji(r.stars)}</Text>
                      <Text type="secondary">
                        {r.updated_at ? new Date(r.updated_at).toLocaleString() : ''}
                      </Text>
                    </Space>
                    {r.comment && <Paragraph>{r.comment}</Paragraph>}
                  </Space>
                </List.Item>
              )}
            />
          )}
        </Card>

        <Alert
          type="info" showIcon
          message="克隆后的 workflow 是独立副本，作者更新原 workflow 不会自动同步过来。"
        />
      </Space>

      <Modal
        open={rateModal}
        title={myRating ? '修改评分' : '提交评分'}
        onOk={submitRating}
        onCancel={() => setRateModal(false)}
        okText="提交"
        cancelText="取消"
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Rate value={stars} onChange={setStars} />
          <Input.TextArea
            rows={4} value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="（可选）分享你的使用体验"
          />
        </Space>
      </Modal>
    </div>
  );
}
