/**
 * F4.1 · Copilot analytics dashboard for admins.
 * URL: /dashboard/copilot/analytics
 */
'use client';
import {
  Alert, Card, Empty, InputNumber, List, Progress, Radio, Space,
  Statistic, Table, Tag, Typography, message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import { useCallback, useEffect, useState } from 'react';

import {
  IntentScore, NegativeFeedback,
  formatScore, getIntentScoreboard, getRecentNegative, scoreTier,
} from '@/lib/copilot_feedback';

dayjs.extend(relativeTime);

const { Text, Title } = Typography;

export default function CopilotAnalyticsPage() {
  const [scoreboard, setScoreboard] = useState<IntentScore[]>([]);
  const [negatives, setNegatives] = useState<NegativeFeedback[]>([]);
  const [loading, setLoading] = useState(false);
  const [minTotal, setMinTotal] = useState(3);
  const [intentFilter, setIntentFilter] = useState<string | undefined>(
    undefined,
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [sb, neg] = await Promise.all([
        getIntentScoreboard(minTotal),
        getRecentNegative({ limit: 30, intent: intentFilter }),
      ]);
      setScoreboard(sb);
      setNegatives(neg);
    } catch (e: any) {
      message.error(`加载失败: ${e?.message ?? e}`);
    } finally {
      setLoading(false);
    }
  }, [minTotal, intentFilter]);

  useEffect(() => { void load(); }, [load]);

  const total = scoreboard.reduce((s, x) => s + x.total, 0);
  const totalUp = scoreboard.reduce((s, x) => s + x.up, 0);
  const totalDown = scoreboard.reduce((s, x) => s + x.down, 0);
  const overallScore = total > 0 ? (totalUp - totalDown) / total : 0;

  const columns: ColumnsType<IntentScore> = [
    {
      title: '意图 (intent)', dataIndex: 'intent',
      render: (v: string) => (
        <Tag
          color={intentFilter === v ? 'blue' : 'default'}
          style={{ cursor: 'pointer' }}
          onClick={() => setIntentFilter(
            intentFilter === v ? undefined : v,
          )}
        >
          {v}
        </Tag>
      ),
    },
    { title: '总数', dataIndex: 'total', width: 80 },
    {
      title: '👍 / 👎',
      render: (_: unknown, r: IntentScore) => (
        <Text>{r.up} / <Text type="danger">{r.down}</Text></Text>
      ),
    },
    {
      title: '好评率',
      render: (_: unknown, r: IntentScore) => (
        <Progress
          percent={r.total > 0
            ? Math.round((r.up / r.total) * 100) : 0}
          size="small" style={{ width: 120 }}
          strokeColor={
            r.score >= 0.5 ? '#52c41a' :
              r.score >= 0 ? '#faad14' : '#ff4d4f'
          }
        />
      ),
    },
    {
      title: '得分',
      dataIndex: 'score',
      render: (_: unknown, r: IntentScore) => {
        const t = scoreTier(r.score);
        return (
          <Tag color={t.color}>
            {t.label} · {formatScore(r.score)}
          </Tag>
        );
      },
    },
  ];

  return (
    <div style={{ padding: 16 }}>
      <Title level={4}>🤖 Copilot 反馈分析</Title>
      <Alert
        type="info" showIcon closable
        style={{ marginBottom: 12 }}
        message="用户对每条 Copilot 回复的 👍/👎 汇总,
          用来定位需要迭代的 intent."
      />

      <Space size="large" style={{ marginBottom: 12 }}>
        <Statistic
          title="总反馈数" value={total} loading={loading}
        />
        <Statistic
          title="👍"
          value={totalUp}
          valueStyle={{ color: '#52c41a' }}
        />
        <Statistic
          title="👎"
          value={totalDown}
          valueStyle={{ color: '#ff4d4f' }}
        />
        <Statistic
          title="整体好评"
          value={formatScore(overallScore)}
          valueStyle={{
            color: overallScore >= 0.5 ? '#52c41a' :
              overallScore >= 0 ? '#faad14' : '#ff4d4f',
          }}
        />
      </Space>

      <Card
        size="small" style={{ marginBottom: 12 }}
        title="Intent 榜单 (最差在前)"
        extra={
          <Space>
            <Text type="secondary">min_total:</Text>
            <InputNumber
              min={1} max={100} value={minTotal}
              onChange={(v) => setMinTotal(v ?? 3)}
              size="small"
            />
          </Space>
        }
      >
        <Table<IntentScore>
          rowKey="intent"
          columns={columns}
          dataSource={scoreboard}
          loading={loading}
          pagination={false}
          size="small"
          locale={{
            emptyText: `尚无 ≥${minTotal} 条反馈的 intent`,
          }}
        />
      </Card>

      <Card
        size="small"
        title={
          <Space>
            <span>最近负反馈</span>
            {intentFilter && (
              <Tag
                color="blue"
                closable
                onClose={() => setIntentFilter(undefined)}
              >
                intent: {intentFilter}
              </Tag>
            )}
          </Space>
        }
      >
        {negatives.length === 0 ? (
          <Empty description={
            intentFilter
              ? `无 "${intentFilter}" 的负反馈`
              : '暂无负反馈 🎉'
          } />
        ) : (
          <List<NegativeFeedback>
            dataSource={negatives}
            renderItem={(n) => (
              <List.Item>
                <List.Item.Meta
                  avatar={
                    <div style={{ fontSize: 20 }}>👎</div>
                  }
                  title={
                    <Space size={6} wrap>
                      <Tag color="volcano">
                        {n.intent ?? '(none)'}
                      </Tag>
                      <Text>{n.user_text}</Text>
                    </Space>
                  }
                  description={
                    <Space direction="vertical" size={2}>
                      {n.reply_text && (
                        <Text
                          type="secondary"
                          style={{ fontSize: 12 }}
                          italic
                        >
                          回复: {n.reply_text.slice(0, 200)}
                        </Text>
                      )}
                      {n.comment && (
                        <Text style={{ fontSize: 12 }}>
                          💬 {n.comment}
                        </Text>
                      )}
                      <Text
                        type="secondary" style={{ fontSize: 12 }}>
                        {n.created_at
                          ? dayjs(n.created_at).fromNow() : ''}
                      </Text>
                    </Space>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Card>
    </div>
  );
}
