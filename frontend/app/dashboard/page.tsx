'use client';

import { useEffect, useRef, useState } from 'react';
import {
  AlertOutlined,
  ArrowUpOutlined,
  FieldTimeOutlined,
  FileSearchOutlined,
  RocketOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { Card, Col, Row, Statistic, Tag, Typography } from 'antd';
import ReactECharts from 'echarts-for-react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { subscribeTelemetry } from '@/lib/ws';

const { Title, Text } = Typography;

type Stats = {
  total_drones: number;
  online_drones: number;
  flight_logs_24h: number;
  missions_today: number;
  pending_approvals: number;
  status_dist: Record<string, number>;
  hourly?: { hour: string; count: number }[];
  per_drone: { drone_id: string; sn: string; online: boolean }[];
};

type LiveMsg = {
  drone_id?: string;
  lat?: number;
  lng?: number;
  alt?: number;
  speed?: number;
  battery?: number;
  ts: string;
};

const STATUS_COLORS: Record<string, string> = {
  idle: 'blue',
  flying: 'green',
  active: 'green',
  online: 'green',
  offline: 'default',
  maintenance: 'orange',
};

export default function DashboardPage() {
  const user = useAuthStore((s) => s.user);
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const res = await api.get('/api/v1/drones/stats');
        if (alive) {
          setStats(res.data);
          setError('');
        }
      } catch (e) {
        if (alive) setError(String(e));
      }
    };
    load();
    const t = setInterval(load, 10000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  // --- A: live WS telemetry stream card ---
  const [wsCount, setWsCount] = useState(0);
  const [wsLast, setWsLast] = useState<LiveMsg | null>(null);
  const [wsOpen, setWsOpen] = useState(false);
  const subscribedRef = useRef(false);
  useEffect(() => {
    if (!stats || subscribedRef.current) return;
    subscribedRef.current = true;
    const subs = stats.per_drone.map((d) =>
      subscribeTelemetry(d.drone_id, (msg) => {
        setWsCount((c) => c + 1);
        setWsLast({ ...msg, ts: new Date().toLocaleTimeString('zh-CN') });
        setWsOpen(true);
      })
    );
    return () => {
      subs.forEach((s) => s.close());
    };
  }, [stats]);

  return (
    <div>
      <Title level={4}>仪表盘 Dashboard</Title>
      <Text type="secondary">
        欢迎回来，{user?.name || user?.email || '用户'}。实时遥测数据流已接入。
        {error ? <Tag color="red">stats 加载失败: {error.slice(0, 60)}</Tag> : null}
      </Text>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="在线设备 Online Drones"
              value={stats ? stats.online_drones : '...'}
              suffix={`/ ${stats ? stats.total_drones : 0}`}
              prefix={<RocketOutlined />}
              valueStyle={{ color: '#52c41a' }}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              近 5 分钟有遥测上报的无人机
            </Text>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="飞行记录(24h) Telemetry"
              value={stats ? stats.flight_logs_24h.toLocaleString() : '...'}
              prefix={<FieldTimeOutlined />}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              全部无人机遥测入库条数
            </Text>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="今日任务 Missions"
              value={stats ? stats.missions_today : '...'}
              prefix={<ArrowUpOutlined />}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              今日创建的飞行任务
            </Text>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="待审批 Pending"
              value={stats ? stats.pending_approvals : '...'}
              prefix={<FileSearchOutlined />}
              valueStyle={{ color: '#faad14' }}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              等待处理的飞行报备申请
            </Text>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={8}>
          <Card
            title={
              <span>
                <ThunderboltOutlined style={{ color: '#1677ff' }} /> 遥测数据流{' '}
                <Tag color={wsOpen ? 'green' : 'default'}>
                  {wsOpen ? 'WS 实时' : '等待数据'}
                </Tag>
              </span>
            }
            size="small"
          >
            <Statistic
              title="本次会话收到消息"
              value={wsCount}
              valueStyle={{ color: wsCount > 0 ? '#1677ff' : undefined }}
            />
            {wsLast ? (
              <div
                style={{
                  marginTop: 10,
                  fontSize: 12,
                  fontFamily: 'monospace',
                  lineHeight: 1.9,
                }}
              >
                <div>lat: {wsLast.lat?.toFixed(5)}</div>
                <div>lng: {wsLast.lng?.toFixed(5)}</div>
                <div>alt: {wsLast.alt?.toFixed(1)} m</div>
                <div>bat: {wsLast.battery ?? '-'}%</div>
                <div style={{ color: '#888' }}>更新于 {wsLast.ts}</div>
              </div>
            ) : (
              <Text type="secondary" style={{ fontSize: 12 }}>
                等待 WebSocket 推送…
              </Text>
            )}
          </Card>
        </Col>
        <Col xs={24} lg={16}>
          <Card title="遥测量趋势（近 24 小时）" size="small">
            <TelemetryTrend hourly={stats?.hourly || []} />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={12}>
          <Card title="设备状态分布 Device Status" size="small">
            {stats && Object.keys(stats.status_dist).length > 0 ? (
              Object.entries(stats.status_dist).map(([s, n]) => (
                <div
                  key={s}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 12,
                    marginBottom: 8,
                  }}
                >
                  <Tag color={STATUS_COLORS[s] || 'default'}>{s}</Tag>
                  <div
                    style={{
                      flex: 1,
                      height: 12,
                      background: '#f0f0f0',
                      borderRadius: 6,
                      overflow: 'hidden',
                    }}
                  >
                    <div
                      style={{
                        width: `${
                          (100 * n) / Math.max(1, stats.total_drones)
                        }%`,
                        height: '100%',
                        background: '#1677ff',
                      }}
                    />
                  </div>
                  <Text strong>{n} 台</Text>
                </div>
              ))
            ) : (
              <Text type="secondary">加载中…</Text>
            )}
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="无人机遥测在线情况 Per-Drone" size="small">
            {stats && stats.per_drone.length > 0 ? (
              stats.per_drone.map((d) => (
                <div
                  key={d.drone_id}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    padding: '6px 0',
                    borderBottom: '1px solid #f5f5f5',
                  }}
                >
                  <Text copyable style={{ fontFamily: 'monospace' }}>
                    {d.sn}
                  </Text>
                  <Tag
                    color={d.online ? 'green' : 'default'}
                    icon={<AlertOutlined />}
                  >
                    {d.online ? '遥测在线' : '无数据'}
                  </Tag>
                </div>
              ))
            ) : (
              <Text type="secondary">加载中…</Text>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );
}

function TelemetryTrend({
  hourly,
}: {
  hourly: { hour: string; count: number }[];
}) {
  if (hourly.length === 0) {
    return <Text type="secondary">暂无数据（等待遥测入库聚合…）</Text>;
  }
  const labels = hourly.map((h) => h.hour.slice(11) + ':00');
  const counts = hourly.map((h) => h.count);
  const option = {
    grid: { left: 48, right: 16, top: 24, bottom: 28 },
    tooltip: { trigger: 'axis' as const },
    xAxis: { type: 'category' as const, data: labels },
    yAxis: { type: 'value' as const },
    series: [
      {
        type: 'line' as const,
        data: counts,
        smooth: true,
        areaStyle: { opacity: 0.15 },
        itemStyle: { color: '#1677ff' },
      },
    ],
  };
  return (
    <ReactECharts
      option={option}
      style={{ height: 220 }}
      opts={{ renderer: 'svg' }}
    />
  );
}
