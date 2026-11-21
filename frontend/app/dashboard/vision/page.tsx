'use client';

import React, { useEffect, useState } from 'react';
import {
  Card, Space, Typography, Button, Table, Tag, message, Input, Select,
  Statistic, Row, Col, Alert, Popconfirm,
} from 'antd';
import {
  EyeOutlined, ThunderboltOutlined, CheckOutlined, CloseOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import {
  getVisionRuntimes, visionInfer, listDetections, ackDetection,
  type VisionDetectionOut,
} from '@/lib/api';
import { useVisionStream } from '@/lib/useVisionStream';
import { BBoxOverlay } from '@/components/BBoxOverlay';

const { Title, Text, Paragraph } = Typography;

const LABEL_COLORS: Record<string, string> = {
  person: 'blue', vehicle: 'cyan', vessel: 'geekblue',
  fire: 'red', smoke: 'orange', crack: 'volcano',
  solar_panel: 'gold', power_line: 'purple',
  helmet: 'green', unknown_object: 'default',
};

export default function VisionPage() {
  const [runtime, setRuntime] = useState<{
    available: string[]; active: string; persist_threshold: number;
  } | null>(null);
  const [detections, setDetections] = useState<VisionDetectionOut[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<{ label?: string; status?: string }>({});
  const [hint, setHint] = useState('');
  const [inferring, setInferring] = useState(false);
  const [lastResult, setLastResult] = useState<any>(null);
  const stream = useVisionStream();  // fleet-wide global feed

  const load = async () => {
    setLoading(true);
    try {
      const [r, ds] = await Promise.all([
        getVisionRuntimes(),
        listDetections({
          ...filter, since_minutes: 60, limit: 100,
        }),
      ]);
      setRuntime(r);
      setDetections(ds);
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '加载失败');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [filter.label, filter.status]);

  const onInfer = async () => {
    setInferring(true);
    try {
      // Send a synthetic frame — the mock runtime is deterministic on bytes.
      const rnd = Math.random().toString(36).slice(2);
      const b64 = 'data:image/png;base64,' + btoa(`sim-frame-${rnd}`);
      const res = await visionInfer({ image_b64: b64, hint: hint || undefined, persist: true });
      setLastResult(res);
      message.success(`识别完成 · ${res.detections.length} 个目标 · ${res.latency_ms.toFixed(1)}ms`);
      load();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '推理失败');
    } finally {
      setInferring(false);
    }
  };

  const onAck = async (id: string, status: string) => {
    try {
      await ackDetection(id, status);
      message.success(`已标记为 ${status}`);
      load();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '操作失败');
    }
  };

  const stats = React.useMemo(() => {
    const s = { total: detections.length, hi: 0, fire: 0, person: 0, veh: 0 };
    for (const d of detections) {
      if (d.confidence >= 0.85) s.hi++;
      if (d.label === 'fire' || d.label === 'smoke') s.fire++;
      if (d.label === 'person') s.person++;
      if (d.label === 'vehicle' || d.label === 'vessel') s.veh++;
    }
    return s;
  }, [detections]);

  const columns = [
    {
      title: '时间', dataIndex: 'created_at', width: 160,
      render: (t: string) => new Date(t).toLocaleString('zh-CN'),
    },
    {
      title: '目标', dataIndex: 'label', width: 120,
      render: (l: string) => <Tag color={LABEL_COLORS[l] || 'default'}>{l}</Tag>,
    },
    {
      title: '置信度', dataIndex: 'confidence', width: 100,
      render: (c: number) => (
        <Tag color={c >= 0.85 ? 'success' : c >= 0.7 ? 'processing' : 'default'}>
          {(c * 100).toFixed(1)}%
        </Tag>
      ),
    },
    {
      title: '位置', width: 180,
      render: (_: any, r: VisionDetectionOut) => (
        r.lat != null && r.lng != null
          ? <Text code>{r.lat.toFixed(5)}, {r.lng.toFixed(5)}</Text>
          : <Text type="secondary">—</Text>
      ),
    },
    { title: '模型', dataIndex: 'model_tag', width: 140 },
    { title: '运行时', dataIndex: 'runtime', width: 90 },
    {
      title: '状态', dataIndex: 'status', width: 100,
      render: (s: string) => {
        const map: any = {
          new: { c: 'processing', t: '新' },
          acknowledged: { c: 'success', t: '已确认' },
          dismissed: { c: 'default', t: '忽略' },
          escalated: { c: 'error', t: '升级' },
        };
        const m = map[s] || { c: 'default', t: s };
        return <Tag color={m.c}>{m.t}</Tag>;
      },
    },
    {
      title: '操作', width: 220,
      render: (_: any, r: VisionDetectionOut) => (
        <Space size={4}>
          <Button size="small" icon={<CheckOutlined />}
                  onClick={() => onAck(r.id, 'acknowledged')}>
            确认
          </Button>
          <Popconfirm title="升级为告警?"
                      onConfirm={() => onAck(r.id, 'escalated')}>
            <Button size="small" danger icon={<WarningOutlined />}>升级</Button>
          </Popconfirm>
          <Button size="small" icon={<CloseOutlined />}
                  onClick={() => onAck(r.id, 'dismissed')}>
            忽略
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <div>
          <Title level={3}>
            <EyeOutlined /> Vision AI · 边缘识别
          </Title>
          <Text type="secondary">
            {runtime && (
              <>当前运行时 <Tag color="blue">{runtime.active}</Tag>
                · 持久化阈值 {runtime.persist_threshold * 100}%
                · 可选：{runtime.available.join(' / ')}</>
            )}
          </Text>
        </div>

        <Row gutter={16}>
          <Col span={6}><Card size="small"><Statistic title="近1小时检测数" value={stats.total} /></Card></Col>
          <Col span={6}><Card size="small"><Statistic title="高置信度 (≥85%)" value={stats.hi} valueStyle={{ color: '#3f8600' }} /></Card></Col>
          <Col span={6}><Card size="small"><Statistic title="火灾/烟雾" value={stats.fire} valueStyle={{ color: '#cf1322' }} /></Card></Col>
          <Col span={6}><Card size="small"><Statistic title="车辆/船只" value={stats.veh} /></Card></Col>
        </Row>

        <Card title="🎬 实时视频流叠加（WebSocket）" size="small"
              extra={
                <Text type="secondary">
                  {stream.connected ? '● 已连接' : '○ 未连接'} · 缓冲 {stream.frames.length} 帧
                  {stream.latest && (
                    <> · {stream.latest.runtime}
                      · {stream.latest.latency_ms.toFixed(1)}ms
                      · {stream.latest.count} 目标</>
                  )}
                </Text>
              }>
          <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
            <BBoxOverlay
              width={640}
              height={360}
              detections={stream.latest?.detections || []}
            />
            <div style={{ flex: 1 }}>
              <Text type="secondary">
                此视图订阅 <Text code>ws://.../ws/vision</Text> 全局通道。
                每次 <Text code>POST /vision/infer</Text> 都会广播 bbox 事件，
                Canvas 以归一化坐标叠加。生产环境可将其覆盖到 WebRTC 视频面板上。
              </Text>
              {stream.latest?.detections?.length ? (
                <div style={{ marginTop: 12 }}>
                  <Text strong>最近一帧：</Text>
                  <ul style={{ marginTop: 4, paddingLeft: 20 }}>
                    {stream.latest.detections.slice(0, 5).map((d, i) => (
                      <li key={i}>
                        <Tag color={LABEL_COLORS[d.label] || 'default'}>{d.label}</Tag>
                        {(d.confidence * 100).toFixed(1)}%
                        {d.track_id != null && <Text type="secondary"> (id={d.track_id})</Text>}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          </div>
        </Card>

        <Card title="⚡ 快速推理测试" size="small">
          <Space>
            <Text>目标提示（可选）：</Text>
            <Input
              placeholder="e.g. person / fire / vehicle"
              value={hint}
              onChange={(e) => setHint(e.target.value)}
              style={{ width: 200 }}
            />
            <Button type="primary" icon={<ThunderboltOutlined />}
                    loading={inferring} onClick={onInfer}>
              推理一帧（mock）
            </Button>
            {lastResult && (
              <Text type="secondary">
                上次：{lastResult.detections.length} 目标 · {lastResult.latency_ms.toFixed(2)}ms
                · 持久化 {lastResult.persisted.length}
              </Text>
            )}
          </Space>
        </Card>

        <Card
          title="🎯 检测事件流"
          size="small"
          extra={
            <Space>
              <Select
                placeholder="按标签"
                allowClear style={{ width: 140 }}
                value={filter.label}
                onChange={(v) => setFilter({ ...filter, label: v })}
                options={Object.keys(LABEL_COLORS).map(k => ({ value: k, label: k }))}
              />
              <Select
                placeholder="按状态"
                allowClear style={{ width: 120 }}
                value={filter.status}
                onChange={(v) => setFilter({ ...filter, status: v })}
                options={[
                  { value: 'new', label: '新' },
                  { value: 'acknowledged', label: '已确认' },
                  { value: 'escalated', label: '升级' },
                  { value: 'dismissed', label: '忽略' },
                ]}
              />
              <Button onClick={load}>刷新</Button>
            </Space>
          }
        >
          <Table
            rowKey="id"
            columns={columns as any}
            dataSource={detections}
            loading={loading}
            size="small"
            pagination={{ pageSize: 20 }}
          />
        </Card>
      </Space>
    </div>
  );
}
