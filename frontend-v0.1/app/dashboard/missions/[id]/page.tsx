'use client';

import React, { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import {
  Card,
  Table,
  Button,
  Tag,
  Space,
  Row,
  Col,
  Typography,
  Descriptions,
  message,
  Spin,
} from 'antd';
import dayjs from 'dayjs';
import {
  getMission,
  getMissionLogs,
  validateMission,
  dispatchMission,
  abortMission,
} from '@/lib/api';
import CesiumMap from '@/components/CesiumMap';

const { Title } = Typography;

const statusColor: Record<string, string> = {
  draft: 'default',
  pending: 'gold',
  running: 'blue',
  completed: 'green',
  failed: 'red',
  cancelled: 'default',
};

interface Waypoint {
  seq?: number;
  lat?: number;
  lng?: number;
  alt?: number;
  action?: string;
  [k: string]: any;
}

interface Mission {
  id: string;
  name: string;
  status: string;
  drone_id?: string;
  drone_sn?: string;
  created_at?: string;
  waypoints?: Waypoint[];
  [k: string]: any;
}

interface FlightLog {
  id?: string;
  ts?: string;
  timestamp?: string;
  level?: string;
  event?: string;
  message?: string;
  [k: string]: any;
}

export default function MissionDetailPage() {
  const params = useParams<{ id: string }>();
  const missionId = params?.id as string;

  const [mission, setMission] = useState<Mission | null>(null);
  const [logs, setLogs] = useState<FlightLog[]>([]);
  const [loading, setLoading] = useState(false);
  const [logsLoading, setLogsLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const fetchMission = async () => {
    if (!missionId) return;
    setLoading(true);
    try {
      const data = await getMission(missionId);
      setMission(data);
    } catch (err: any) {
      message.error(err?.message || '加载任务详情失败');
    } finally {
      setLoading(false);
    }
  };

  const fetchLogs = async () => {
    if (!missionId) return;
    setLogsLoading(true);
    try {
      const data = await getMissionLogs(missionId, 10);
      const list = Array.isArray(data) ? data : data?.items || [];
      setLogs(list);
    } catch (err: any) {
      // logs may 404 for new missions — not fatal
      setLogs([]);
    } finally {
      setLogsLoading(false);
    }
  };

  useEffect(() => {
    fetchMission();
    fetchLogs();
  }, [missionId]);

  const handleAction = async (
    action: 'validate' | 'dispatch' | 'abort',
    fn: (id: string) => Promise<any>,
    label: string
  ) => {
    setActionLoading(action);
    try {
      await fn(missionId);
      message.success(`${label}成功`);
      await fetchMission();
      await fetchLogs();
    } catch (err: any) {
      message.error(err?.response?.data?.detail || err?.message || `${label}失败`);
    } finally {
      setActionLoading(null);
    }
  };

  const waypointColumns = [
    { title: '#', dataIndex: 'seq', key: 'seq', width: 60, render: (v: any, _r: any, i: number) => v ?? i + 1 },
    { title: '纬度', dataIndex: 'lat', key: 'lat', render: (v?: number) => (v != null ? v.toFixed(6) : '-') },
    { title: '经度', dataIndex: 'lng', key: 'lng', render: (v?: number) => (v != null ? v.toFixed(6) : '-') },
    { title: '高度(m)', dataIndex: 'alt', key: 'alt', render: (v?: number) => (v != null ? v : '-') },
    { title: '动作', dataIndex: 'action', key: 'action', render: (v?: string) => v || '-' },
  ];

  const logColumns = [
    {
      title: '时间',
      dataIndex: 'ts',
      key: 'ts',
      width: 180,
      render: (v: string, r: FlightLog) => {
        const t = v || r.timestamp;
        return t ? dayjs(t).format('YYYY-MM-DD HH:mm:ss') : '-';
      },
    },
    {
      title: '级别',
      dataIndex: 'level',
      key: 'level',
      width: 100,
      render: (v?: string) => v ? <Tag>{v}</Tag> : '-',
    },
    { title: '事件', dataIndex: 'event', key: 'event', render: (v?: string) => v || '-' },
    { title: '消息', dataIndex: 'message', key: 'message', render: (v?: string) => v || '-' },
  ];

  const waypoints: Waypoint[] = mission?.waypoints || [];

  return (
    <Spin spinning={loading}>
      <div style={{ padding: 24 }}>
        <Title level={3} style={{ marginBottom: 16 }}>
          任务详情
        </Title>
        <Row gutter={16}>
          <Col xs={24} lg={14}>
            <Card title="航点列表" style={{ marginBottom: 16 }}>
              <Table
                rowKey={(r, i) => r.seq?.toString() || String(i)}
                size="small"
                columns={waypointColumns}
                dataSource={waypoints}
                pagination={false}
                locale={{ emptyText: '暂无航点' }}
              />
            </Card>
            <Card title="3D 地图" bodyStyle={{ padding: 0 }}>
              <CesiumMap
                waypoints={waypoints.filter(
                  (w): w is Required<Pick<Waypoint, 'lat' | 'lng'>> & Waypoint =>
                    typeof w.lat === 'number' && typeof w.lng === 'number'
                ).map((w) => ({
                  seq: w.seq ?? 0,
                  lat: w.lat!,
                  lng: w.lng!,
                  alt: w.alt ?? 0,
                }))}
                droneId={mission?.drone_id}
                height={600}
              />
            </Card>
          </Col>
          <Col xs={24} lg={10}>
            <Card
              title="任务信息"
              style={{ marginBottom: 16 }}
              extra={
                mission?.status ? (
                  <Tag color={statusColor[mission.status] || 'default'}>{mission.status}</Tag>
                ) : null
              }
            >
              <Descriptions column={1} size="small">
                <Descriptions.Item label="任务名">{mission?.name || '-'}</Descriptions.Item>
                <Descriptions.Item label="任务ID">{mission?.id || missionId}</Descriptions.Item>
                <Descriptions.Item label="状态">
                  {mission?.status ? (
                    <Tag color={statusColor[mission.status] || 'default'}>{mission.status}</Tag>
                  ) : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="设备">
                  {mission?.drone_sn || mission?.drone_id || '-'}
                </Descriptions.Item>
                <Descriptions.Item label="创建时间">
                  {mission?.created_at
                    ? dayjs(mission.created_at).format('YYYY-MM-DD HH:mm:ss')
                    : '-'}
                </Descriptions.Item>
              </Descriptions>
            </Card>
            <Card title="任务操作">
              <Space wrap>
                <Button
                  type="default"
                  loading={actionLoading === 'validate'}
                  onClick={() => handleAction('validate', validateMission, '校验')}
                >
                  校验 Validate
                </Button>
                <Button
                  type="primary"
                  loading={actionLoading === 'dispatch'}
                  onClick={() => handleAction('dispatch', dispatchMission, '下发')}
                >
                  下发 Dispatch
                </Button>
                <Button
                  danger
                  loading={actionLoading === 'abort'}
                  onClick={() => handleAction('abort', abortMission, '中止')}
                >
                  中止 Abort
                </Button>
              </Space>
            </Card>
          </Col>
        </Row>
        <Card title="最近飞行日志 (最多10条)" style={{ marginTop: 16 }}>
          <Table
            rowKey={(r, i) => r.id?.toString() || String(i)}
            size="small"
            loading={logsLoading}
            columns={logColumns}
            dataSource={logs}
            pagination={false}
            locale={{ emptyText: '暂无日志' }}
          />
        </Card>
      </div>
    </Spin>
  );
}
