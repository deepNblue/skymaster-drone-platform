'use client';

/**
 * Deployment usage dashboard — T6.6.
 * Path: /dashboard/model-marketplace/deployments/[did]/usage
 *
 * Renders a daily-usage bar chart (SVG, no chart-lib dep) + summary card
 * for one ModelDeployment. Data comes from /usage-daily.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import {
  Card, Space, Typography, Button, Select, Spin, Empty, Result, Tag,
  Row, Col, Statistic, message, Divider,
} from 'antd';
import { ArrowLeftOutlined, ReloadOutlined } from '@ant-design/icons';
import {
  getUsageDaily,
  UsageDailySeries,
  UsageDailyPoint,
} from '@/lib/model_marketplace';

const { Text, Title, Paragraph } = Typography;

// Outcome → color palette (stable across bars/legend).
const OUTCOME_COLOR: Record<string, string> = {
  ok: '#52c41a',
  error: '#f5222d',
  timeout: '#faad14',
  throttled: '#722ed1',
};
const DEFAULT_COLOR = '#8c8c8c';

function outcomeColor(o: string): string {
  return OUTCOME_COLOR[o] ?? DEFAULT_COLOR;
}

/**
 * Minimal responsive-ish stacked bar chart. Renders one bar per day.
 * `maxY` optionally forces the y-axis top (for the quota reference line).
 */
function DailyBarChart({
  points,
  quota,
  height = 260,
}: {
  points: UsageDailyPoint[];
  quota: number | null;
  height?: number;
}) {
  const outcomes = useMemo(() => {
    const s = new Set<string>();
    points.forEach((p) => Object.keys(p.by_outcome).forEach((k) => s.add(k)));
    return Array.from(s).sort();
  }, [points]);

  const maxUsage = Math.max(1, ...points.map((p) => p.total_units));
  const yMax = quota && quota > 0 ? Math.max(maxUsage, quota) : maxUsage;

  const width = Math.max(600, points.length * 24);
  const paddingLeft = 44;
  const paddingBottom = 24;
  const paddingTop = 12;
  const chartH = height - paddingTop - paddingBottom;
  const barW = points.length > 0
    ? (width - paddingLeft - 8) / points.length
    : 0;

  return (
    <div style={{ width: '100%', overflowX: 'auto' }}>
      <svg
        width={width}
        height={height}
        role="img"
        aria-label="Daily usage bar chart"
      >
        {/* Y grid + labels */}
        {[0, 0.25, 0.5, 0.75, 1].map((r) => {
          const y = paddingTop + chartH * (1 - r);
          const val = Math.round(yMax * r);
          return (
            <g key={r}>
              <line
                x1={paddingLeft}
                x2={width - 4}
                y1={y}
                y2={y}
                stroke="#f0f0f0"
              />
              <text
                x={paddingLeft - 6}
                y={y + 3}
                fontSize={10}
                textAnchor="end"
                fill="#888"
              >
                {val}
              </text>
            </g>
          );
        })}

        {/* Quota reference line */}
        {quota && quota > 0 && (
          <g>
            <line
              x1={paddingLeft}
              x2={width - 4}
              y1={paddingTop + chartH * (1 - quota / yMax)}
              y2={paddingTop + chartH * (1 - quota / yMax)}
              stroke="#f5222d"
              strokeDasharray="4 3"
              strokeWidth={1}
            />
            <text
              x={width - 6}
              y={paddingTop + chartH * (1 - quota / yMax) - 3}
              fontSize={10}
              textAnchor="end"
              fill="#f5222d"
            >
              日配额 {quota}
            </text>
          </g>
        )}

        {/* Stacked bars */}
        {points.map((p, idx) => {
          const x = paddingLeft + idx * barW + barW * 0.15;
          const w = barW * 0.7;
          let stackTop = 0;
          const heightPx = (v: number) => (v / yMax) * chartH;

          return (
            <g key={p.day}>
              {outcomes.map((o) => {
                const v = p.by_outcome[o] ?? 0;
                if (v <= 0) return null;
                const h = heightPx(v);
                const y = paddingTop + chartH - stackTop - h;
                stackTop += h;
                return (
                  <rect
                    key={o}
                    x={x}
                    y={y}
                    width={w}
                    height={Math.max(1, h)}
                    fill={outcomeColor(o)}
                  >
                    <title>
                      {p.day} · {o}: {v}
                    </title>
                  </rect>
                );
              })}
              {(idx === 0 ||
                idx === points.length - 1 ||
                idx % Math.max(1, Math.floor(points.length / 8)) === 0) && (
                <text
                  x={x + w / 2}
                  y={paddingTop + chartH + 14}
                  fontSize={10}
                  fill="#666"
                  textAnchor="middle"
                >
                  {p.day.slice(5)}
                </text>
              )}
            </g>
          );
        })}
      </svg>

      {/* Legend */}
      <Space wrap style={{ marginTop: 8 }}>
        {outcomes.map((o) => (
          <Space size={4} key={o}>
            <span
              style={{
                display: 'inline-block',
                width: 10,
                height: 10,
                background: outcomeColor(o),
                borderRadius: 2,
              }}
            />
            <Text style={{ fontSize: 12 }}>{o}</Text>
          </Space>
        ))}
      </Space>
    </div>
  );
}

export default function UsageDashboardPage() {
  const params = useParams();
  const router = useRouter();
  const did = params?.did as string;

  const [range, setRange] = useState<number>(30);
  const [data, setData] = useState<UsageDailySeries | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [forbidden, setForbidden] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setNotFound(false);
    setForbidden(false);
    try {
      const d = await getUsageDaily(did, range);
      setData(d);
    } catch (e: any) {
      const st = e?.response?.status;
      if (st === 404) setNotFound(true);
      else if (st === 403) setForbidden(true);
      else
        message.error(`加载失败: ${e?.response?.data?.detail ?? e.message}`);
    } finally {
      setLoading(false);
    }
  }, [did, range]);

  useEffect(() => {
    if (did) load();
  }, [did, load]);

  if (notFound) {
    return (
      <Result
        status="404"
        title="部署不存在"
        subTitle="可能已被卸载，或该 ID 无效。"
        extra={
          <Button
            onClick={() => router.push('/dashboard/model-marketplace')}
          >
            返回商店
          </Button>
        }
      />
    );
  }
  if (forbidden) {
    return (
      <Result
        status="403"
        title="无权访问该部署"
        subTitle="部署由其它组织安装。"
        extra={
          <Button
            onClick={() => router.push('/dashboard/model-marketplace')}
          >
            返回商店
          </Button>
        }
      />
    );
  }

  const totalUnits = data
    ? data.points.reduce((s, p) => s + p.total_units, 0)
    : 0;
  const activeDays = data
    ? data.points.filter((p) => p.total_units > 0).length
    : 0;
  const avgPerDay = data && data.points.length
    ? Math.round(totalUnits / data.points.length)
    : 0;
  // Peak day
  const peak = data
    ? data.points.reduce<UsageDailyPoint | null>(
        (m, p) => (m === null || p.total_units > m.total_units ? p : m),
        null,
      )
    : null;
  // Quota utilisation vs peak (peaks over quota == burst risk).
  const overQuotaDays = data && data.quota_calls_per_day
    ? data.points.filter(
        (p) => p.total_units > (data.quota_calls_per_day as number),
      ).length
    : 0;

  return (
    <div style={{ padding: 16, maxWidth: 1100, margin: '0 auto' }}>
      <Button
        type="link"
        icon={<ArrowLeftOutlined />}
        style={{ paddingLeft: 0, marginBottom: 8 }}
        onClick={() => router.push('/dashboard/model-marketplace')}
      >
        返回商店
      </Button>

      <Card>
        <Space
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            width: '100%',
          }}
        >
          <div>
            <Title level={4} style={{ marginBottom: 4 }}>
              模型部署 · 使用统计
            </Title>
            <Text type="secondary" style={{ fontSize: 12 }}>
              部署 ID: <Text code>{did.slice(0, 8)}…</Text>
              {data?.quota_calls_per_day && (
                <> · 日配额 <Tag color="orange">{data.quota_calls_per_day}</Tag></>
              )}
            </Text>
          </div>
          <Space>
            <Select
              value={range}
              onChange={setRange}
              options={[
                { value: 7, label: '近 7 天' },
                { value: 14, label: '近 14 天' },
                { value: 30, label: '近 30 天' },
                { value: 60, label: '近 60 天' },
                { value: 90, label: '近 90 天' },
              ]}
              style={{ width: 120 }}
            />
            <Button icon={<ReloadOutlined />} onClick={load}>
              刷新
            </Button>
          </Space>
        </Space>

        <Divider style={{ margin: '16px 0' }} />

        <Row gutter={16} style={{ marginBottom: 12 }}>
          <Col span={6}>
            <Statistic title="累计调用量" value={totalUnits} />
          </Col>
          <Col span={6}>
            <Statistic
              title="日均"
              value={avgPerDay}
              suffix={`/ 天`}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="活跃天数"
              value={activeDays}
              suffix={`/ ${data?.points.length ?? 0}`}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title={data?.quota_calls_per_day ? '突破配额天数' : '峰值'}
              value={data?.quota_calls_per_day
                ? overQuotaDays
                : peak?.total_units ?? 0}
              valueStyle={{
                color: data?.quota_calls_per_day && overQuotaDays > 0
                  ? '#f5222d' : undefined,
              }}
            />
          </Col>
        </Row>

        {loading ? (
          <div style={{ textAlign: 'center', padding: 40 }}>
            <Spin />
          </div>
        ) : !data || data.points.length === 0 ? (
          <Empty description="选定时间窗口内没有调用记录" />
        ) : (
          <>
            <DailyBarChart
              points={data.points}
              quota={data.quota_calls_per_day}
            />
            {peak && peak.total_units > 0 && (
              <Paragraph type="secondary" style={{ marginTop: 12, fontSize: 12 }}>
                峰值日: <Text strong>{peak.day}</Text> · {peak.total_units} 次
                {data.quota_calls_per_day &&
                  peak.total_units > data.quota_calls_per_day && (
                    <Tag color="red" style={{ marginLeft: 8 }}>
                      超过日配额
                    </Tag>
                  )}
              </Paragraph>
            )}
          </>
        )}
      </Card>
    </div>
  );
}
