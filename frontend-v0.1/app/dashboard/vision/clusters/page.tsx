/**
 * E3.2 · Vision Detection Cluster analytics dashboard.
 * URL: /dashboard/vision/clusters
 */
'use client';
import {
  Alert, Button, Card, Col, InputNumber, Row, Select, Space, Statistic,
  Table, Tag, Typography, message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  CLUSTER_SEV_COLOR, ClusterAnalytics, DetectionCluster,
  getClusterAnalytics, severityForCluster, toHeatmapGrid, topLabels,
} from '@/lib/detection_cluster';

const { Text } = Typography;

const SEV_LABEL: Record<string, string> = {
  low: '轻微', medium: '中等', high: '严重', critical: '紧急',
};

export default function ClustersPage() {
  const [data, setData] = useState<ClusterAnalytics | null>(null);
  const [loading, setLoading] = useState(false);
  const [windowSec, setWindowSec] = useState(3600);
  const [labelFilter, setLabelFilter] = useState<string | undefined>();
  const [geoTolM, setGeoTolM] = useState(50);
  const [timeTolS, setTimeTolS] = useState(30);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await getClusterAnalytics({
        label: labelFilter,
        since_seconds: windowSec,
        geo_tol_m: geoTolM,
        time_tol_s: timeTolS,
      });
      setData(r);
    } catch (e: any) {
      message.error(`加载失败: ${e?.message ?? e}`);
    } finally {
      setLoading(false);
    }
  }, [labelFilter, windowSec, geoTolM, timeTolS]);

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const clusters = data?.clusters ?? [];
  const heatmap = useMemo(() => toHeatmapGrid(clusters), [clusters]);
  const top = useMemo(() => topLabels(clusters, 5), [clusters]);

  const maxWeight = heatmap[0]?.weight ?? 1;

  const bySev = useMemo(() => {
    const acc: Record<string, number> = {
      low: 0, medium: 0, high: 0, critical: 0,
    };
    for (const c of clusters) {
      acc[severityForCluster(c)] += 1;
    }
    return acc;
  }, [clusters]);

  const cols: ColumnsType<DetectionCluster> = [
    {
      title: '严重度',
      key: 'sev',
      width: 80,
      render: (_, c) => {
        const s = severityForCluster(c);
        return <Tag color={CLUSTER_SEV_COLOR[s]}>{SEV_LABEL[s]}</Tag>;
      },
    },
    {
      title: '类别',
      dataIndex: 'label',
      key: 'label',
      width: 100,
      render: (l: string) => <Text strong>{l}</Text>,
    },
    {
      title: '事件数',
      dataIndex: 'member_count',
      key: 'member_count',
      width: 80,
    },
    {
      title: '峰值 conf',
      dataIndex: 'peak_confidence',
      key: 'peak_confidence',
      width: 100,
      render: (v: number) => v.toFixed(3),
    },
    {
      title: '中心位置',
      key: 'centroid',
      width: 200,
      render: (_, c) =>
        `${c.centroid_lat.toFixed(5)}, ${c.centroid_lng.toFixed(5)}`,
    },
    {
      title: '首次 / 末次',
      key: 'time',
      width: 220,
      render: (_, c) =>
        `${dayjs(c.first_seen_at).format('HH:mm:ss')} → ${
          dayjs(c.last_seen_at).format('HH:mm:ss')
        } (${c.duration_s.toFixed(0)}s)`,
    },
    {
      title: '涉及无人机',
      dataIndex: 'drone_ids',
      key: 'drones',
      render: (ds: string[]) => (
        <Space size={4} wrap>
          {ds.length === 0
            ? <Text type="secondary">—</Text>
            : ds.map((d) => (
              <Tag key={d}>{d.slice(0, 8)}</Tag>
            ))
          }
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 16 }}>
      <Typography.Title level={4}>
        👁️ Vision Detection 聚类分析
      </Typography.Title>

      <Card size="small" style={{ marginBottom: 12 }}>
        <Space wrap>
          <Text>时间窗:</Text>
          <Select value={windowSec} onChange={setWindowSec}
            style={{ width: 120 }}
            options={[
              { label: '最近 5 分钟', value: 300 },
              { label: '最近 1 小时', value: 3600 },
              { label: '最近 6 小时', value: 21_600 },
              { label: '最近 24 小时', value: 86_400 },
            ]}
          />
          <Text>类别:</Text>
          <Select value={labelFilter} allowClear
            style={{ width: 140 }}
            placeholder="所有类别"
            onChange={(v) => setLabelFilter(v ?? undefined)}
            options={[
              'person', 'vehicle', 'fire', 'smoke',
              'solar_panel_defect', 'crack',
            ].map((v) => ({ label: v, value: v }))}
          />
          <Text>空间容差 (m):</Text>
          <InputNumber value={geoTolM} min={10} max={5000}
            step={10} onChange={(v) => setGeoTolM(v ?? 50)}
          />
          <Text>时间容差 (s):</Text>
          <InputNumber value={timeTolS} min={5} max={3600}
            step={5} onChange={(v) => setTimeTolS(v ?? 30)}
          />
          <Button type="primary" loading={loading}
            onClick={() => void load()}>刷新</Button>
        </Space>
      </Card>

      {data && (
        <Card size="small" style={{ marginBottom: 12 }}>
          <Row gutter={16}>
            <Col span={5}>
              <Statistic title="检测总数" value={data.total_detections} />
            </Col>
            <Col span={5}>
              <Statistic title="聚类事件"
                value={data.cluster_count}
                valueStyle={{ color: '#1677ff' }}
              />
            </Col>
            <Col span={4}>
              <Statistic title="紧急" value={bySev.critical}
                valueStyle={{ color: '#a8071a' }}
              />
            </Col>
            <Col span={4}>
              <Statistic title="严重" value={bySev.high}
                valueStyle={{ color: '#fa541c' }}
              />
            </Col>
            <Col span={6}>
              <Statistic title="窗口" value={
                data.window_seconds >= 3600
                  ? `${Math.round(data.window_seconds / 3600)}h`
                  : `${Math.round(data.window_seconds / 60)}min`
              } />
            </Col>
          </Row>
        </Card>
      )}

      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={10}>
          <Card size="small" title="🔥 位置热度栅格">
            {heatmap.length === 0 ? (
              <Alert type="info" showIcon message="暂无热点"/>
            ) : (
              <div style={{
                position: 'relative',
                width: '100%',
                height: 260,
                background: '#0f172a',
                borderRadius: 4,
                overflow: 'hidden',
              }}>
                {heatmap.slice(0, 40).map((cell, i) => {
                  // Simple normalized layout for visual purposes.
                  const lats = heatmap.map((c) => c.lat);
                  const lngs = heatmap.map((c) => c.lng);
                  const minLat = Math.min(...lats);
                  const maxLat = Math.max(...lats);
                  const minLng = Math.min(...lngs);
                  const maxLng = Math.max(...lngs);
                  const dLat = maxLat - minLat || 1e-6;
                  const dLng = maxLng - minLng || 1e-6;
                  const x = ((cell.lng - minLng) / dLng) * 90 + 5;
                  const y = 95 - ((cell.lat - minLat) / dLat) * 90;
                  const r = 8 + (cell.weight / maxWeight) * 30;
                  const opacity =
                    0.35 + (cell.weight / maxWeight) * 0.6;
                  return (
                    <div key={i} title={
                      `${cell.labels.join(',')}: ${cell.weight}`
                    } style={{
                      position: 'absolute',
                      left: `${x}%`,
                      top: `${y}%`,
                      width: r,
                      height: r,
                      marginLeft: -r / 2,
                      marginTop: -r / 2,
                      borderRadius: '50%',
                      background:
                        `radial-gradient(circle, rgba(250,84,28,${opacity}) 0%, rgba(250,84,28,0) 70%)`,
                      pointerEvents: 'auto',
                    }}/>
                  );
                })}
                <div style={{
                  position: 'absolute', bottom: 4, left: 8,
                  color: '#94a3b8', fontSize: 11,
                }}>
                  {heatmap.length} 个热点 (相对布局)
                </div>
              </div>
            )}
          </Card>
        </Col>
        <Col span={14}>
          <Card size="small" title="🏷️ 类别分布 (member share)">
            {top.length === 0 ? (
              <Alert type="info" showIcon message="暂无检测"/>
            ) : (
              <Space direction="vertical" style={{ width: '100%' }}>
                {top.map((t) => (
                  <div key={t.label}>
                    <div style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      marginBottom: 2,
                    }}>
                      <Text strong>{t.label}</Text>
                      <Text type="secondary">
                        {t.total} · {(t.share * 100).toFixed(1)}%
                      </Text>
                    </div>
                    <div style={{
                      width: '100%', height: 8,
                      background: '#f0f0f0', borderRadius: 4,
                      overflow: 'hidden',
                    }}>
                      <div style={{
                        width: `${t.share * 100}%`,
                        height: '100%',
                        background: '#1677ff',
                      }}/>
                    </div>
                  </div>
                ))}
              </Space>
            )}
          </Card>
        </Col>
      </Row>

      <Card size="small" title="📋 聚类事件列表">
        <Table<DetectionCluster>
          rowKey={(c) => `${c.label}-${c.first_seen_at}`}
          size="small"
          loading={loading}
          columns={cols}
          dataSource={clusters}
          pagination={{ pageSize: 20 }}
        />
      </Card>
    </div>
  );
}
