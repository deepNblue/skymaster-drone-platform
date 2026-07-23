'use client';

/**
 * MetricsPanel — Prometheus /metrics live dashboard for v1.0 monitoring.
 *
 * Polls /api/v1/metrics every 5s, parses the four metrics we care about
 * for the ops view:
 *   - HTTP p50/p95 latency
 *   - Total missions dispatched
 *   - Geofence blocks (by kind)
 *   - UOM report status counts
 *
 * Renders as a small right-drawer accessible via a floating button.
 */
import React, { useEffect, useState } from 'react';
import { Button, Drawer, Statistic, Row, Col, Tag, Divider } from 'antd';
import { LineChartOutlined } from '@ant-design/icons';
import { api } from '@/lib/api';

interface ParsedMetrics {
  missionsDispatched: number;
  geofenceBlocks: Record<string, number>;
  uomStatuses: Record<string, number>;
  httpTotalReqs: number;
  httpErrorRate: number;
  latencyP95Sec: number;
}

function parseMetrics(text: string): ParsedMetrics {
  const lines = text.split('\n');
  const result: ParsedMetrics = {
    missionsDispatched: 0,
    geofenceBlocks: {},
    uomStatuses: {},
    httpTotalReqs: 0,
    httpErrorRate: 0,
    latencyP95Sec: 0,
  };

  let totalReqs = 0;
  let errorReqs = 0;
  const latBuckets: Record<string, number> = {};
  let latCount = 0;

  for (const line of lines) {
    if (line.startsWith('#') || !line.trim()) continue;
    const spaceIdx = line.lastIndexOf(' ');
    if (spaceIdx < 0) continue;
    const key = line.slice(0, spaceIdx);
    const val = parseFloat(line.slice(spaceIdx + 1));
    if (isNaN(val)) continue;

    if (key.startsWith('skymaster_missions_dispatched_total')) {
      result.missionsDispatched = val;
    } else if (key.startsWith('skymaster_geofence_blocks_total{')) {
      const m = key.match(/kind="([^"]+)"/);
      if (m) result.geofenceBlocks[m[1]] = val;
    } else if (key.startsWith('skymaster_uom_reports_total{')) {
      const m = key.match(/status="([^"]+)"/);
      if (m) result.uomStatuses[m[1]] = val;
    } else if (key.startsWith('skymaster_http_requests_total{')) {
      totalReqs += val;
      const s = key.match(/status="([^"]+)"/);
      if (s && (s[1].startsWith('4') || s[1].startsWith('5'))) errorReqs += val;
    } else if (key.startsWith('skymaster_http_request_duration_seconds_bucket{')) {
      const le = key.match(/le="([^"]+)"/);
      if (le) {
        latBuckets[le[1]] = (latBuckets[le[1]] || 0) + val;
      }
    } else if (key.startsWith('skymaster_http_request_duration_seconds_count')) {
      latCount += val;
    }
  }

  result.httpTotalReqs = totalReqs;
  if (totalReqs > 0) result.httpErrorRate = (errorReqs / totalReqs) * 100;

  // Approximate p95 via bucket cumulative counts.
  if (latCount > 0) {
    const target = latCount * 0.95;
    const boundsOrdered = Object.keys(latBuckets)
      .filter((b) => b !== '+Inf')
      .map((b) => parseFloat(b))
      .sort((a, b) => a - b);
    for (const b of boundsOrdered) {
      if ((latBuckets[String(b)] || 0) >= target) {
        result.latencyP95Sec = b;
        break;
      }
    }
  }
  return result;
}

export default function MetricsPanel() {
  const [open, setOpen] = useState(false);
  const [metrics, setMetrics] = useState<ParsedMetrics | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    const load = async () => {
      try {
        const r = await api.get('/api/v1/metrics', { responseType: 'text' });
        if (cancelled) return;
        setMetrics(parseMetrics(r.data as string));
        setErr(null);
      } catch (e: any) {
        setErr(e?.message || String(e));
      }
    };
    load();
    const id = setInterval(load, 5000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [open]);

  return (
    <>
      <Button
        icon={<LineChartOutlined />}
        onClick={() => setOpen(true)}
        style={{
          position: 'absolute',
          top: 60,
          right: 16,
          zIndex: 25,
          background: 'rgba(13,17,23,0.9)',
          border: '1px solid #21262d',
          color: '#e6edf3',
        }}
      >
        📊 监控
      </Button>

      <Drawer
        title="📊 平台监控 · Prometheus /metrics"
        placement="right"
        onClose={() => setOpen(false)}
        open={open}
        width={420}
      >
        {err && <Tag color="red">加载失败：{err}</Tag>}
        {metrics && (
          <>
            <Row gutter={16}>
              <Col span={12}>
                <Statistic
                  title="总请求"
                  value={metrics.httpTotalReqs}
                  precision={0}
                />
              </Col>
              <Col span={12}>
                <Statistic
                  title="错误率"
                  value={metrics.httpErrorRate}
                  precision={2}
                  suffix="%"
                  valueStyle={{
                    color: metrics.httpErrorRate > 5 ? '#cf1322' : '#3f8600',
                  }}
                />
              </Col>
            </Row>
            <Divider style={{ margin: '12px 0' }} />
            <Row gutter={16}>
              <Col span={12}>
                <Statistic
                  title="P95 延迟"
                  value={(metrics.latencyP95Sec * 1000).toFixed(0)}
                  suffix="ms"
                />
              </Col>
              <Col span={12}>
                <Statistic
                  title="任务派发"
                  value={metrics.missionsDispatched}
                />
              </Col>
            </Row>

            <Divider style={{ margin: '16px 0 8px' }}>UOM 报备</Divider>
            {Object.keys(metrics.uomStatuses).length === 0 ? (
              <Tag>暂无</Tag>
            ) : (
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {Object.entries(metrics.uomStatuses).map(([k, v]) => (
                  <Tag
                    key={k}
                    color={
                      k === 'approved' ? 'green' : k === 'rejected' ? 'red' : 'blue'
                    }
                  >
                    {k}: {v}
                  </Tag>
                ))}
              </div>
            )}

            <Divider style={{ margin: '16px 0 8px' }}>禁飞区拦截</Divider>
            {Object.keys(metrics.geofenceBlocks).length === 0 ? (
              <Tag color="green">无拦截</Tag>
            ) : (
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {Object.entries(metrics.geofenceBlocks).map(([k, v]) => (
                  <Tag key={k} color="volcano">
                    {k}: {v}
                  </Tag>
                ))}
              </div>
            )}
            <p style={{ marginTop: 20, color: '#7d8590', fontSize: 12 }}>
              5s 自动刷新 · 数据来源 /api/v1/metrics
            </p>
          </>
        )}
      </Drawer>
    </>
  );
}
