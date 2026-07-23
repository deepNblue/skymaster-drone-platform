'use client';

/**
 * E2.6 · Workflow 市场浏览页.
 */
import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import {
  Card, Col, Empty, Input, Row, Select, Space, Tag, Typography, message,
} from 'antd';
import {
  browse, formatRating, starEmoji, visibilityBadge,
  type Listing,
} from '@/lib/copilot_workflow_marketplace';

const { Title, Text, Paragraph } = Typography;
const { Search } = Input;

type OrderBy = 'install_count' | 'avg_rating' | 'published_at';

export default function MarketplacePage(): React.ReactElement {
  const [items, setItems] = useState<Listing[]>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState('');
  const [orderBy, setOrderBy] = useState<OrderBy>('install_count');
  const [loading, setLoading] = useState(false);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const r = await browse({ q: q || undefined, order_by: orderBy });
      setItems(r.items);
      setTotal(r.total);
    } catch (e) {
      message.error(String(e));
    } finally {
      setLoading(false);
    }
  }, [q, orderBy]);

  useEffect(() => { reload(); }, [reload]);

  return (
    <div style={{ padding: 24 }}>
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        <Title level={3}>Copilot Workflow 市场</Title>
        <Text type="secondary">
          浏览、克隆、评分其他团队共享的 Copilot workflow。
        </Text>

        <Space wrap>
          <Search
            placeholder="按标题/摘要搜索" allowClear
            style={{ width: 320 }}
            onSearch={setQ}
          />
          <Select
            value={orderBy}
            onChange={(v) => setOrderBy(v as OrderBy)}
            options={[
              { value: 'install_count', label: '安装量优先' },
              { value: 'avg_rating', label: '评分优先' },
              { value: 'published_at', label: '最新发布' },
            ]}
            style={{ width: 160 }}
          />
        </Space>

        <Text type="secondary">共 {total} 条结果</Text>

        {items.length === 0 && !loading ? (
          <Empty description="暂无匹配的 workflow" />
        ) : (
          <Row gutter={[16, 16]}>
            {items.map((it) => {
              const vb = visibilityBadge(it.visibility);
              return (
                <Col key={it.id} xs={24} sm={12} lg={8}>
                  <Link
                    href={`/dashboard/copilot-marketplace/${it.id}`}
                    style={{ textDecoration: 'none' }}
                  >
                    <Card hoverable title={
                      <Space>
                        <span>{it.title}</span>
                        <Tag color={vb.color}>{vb.text}</Tag>
                      </Space>
                    }>
                      <Paragraph ellipsis={{ rows: 2 }} type="secondary">
                        {it.summary || '（无描述）'}
                      </Paragraph>
                      <Space wrap size="small">
                        {(it.tags ?? []).map((t) => (
                          <Tag key={t}>{t}</Tag>
                        ))}
                      </Space>
                      <div style={{ marginTop: 12 }}>
                        <Text>{starEmoji(it.avg_rating)}</Text>
                        <Text type="secondary" style={{ marginLeft: 8 }}>
                          {formatRating(it.avg_rating, it.rating_count)}
                        </Text>
                        <Text type="secondary" style={{ float: 'right' }}>
                          安装 {it.install_count}
                        </Text>
                      </div>
                    </Card>
                  </Link>
                </Col>
              );
            })}
          </Row>
        )}
      </Space>
    </div>
  );
}
