'use client';

/**
 * VisionToolResult — Rich renderer for Copilot v2 vision-AI tool results.
 *
 * Handles two tool names:
 *   - list_detections → colored label tags + confidence + timestamps
 *   - detection_stats → total + top_label + label-count list
 *
 * When neither shape matches, falls back to a code snippet.
 */
import React from 'react';
import { Tag, Typography, Space, Divider, Statistic } from 'antd';
import {
  EyeOutlined,
  BarChartOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons';

const { Text } = Typography;

const LABEL_COLORS: Record<string, string> = {
  person: 'blue',
  vehicle: 'cyan',
  vessel: 'geekblue',
  fire: 'red',
  smoke: 'orange',
  crack: 'volcano',
  solar_panel: 'gold',
  power_line: 'purple',
  helmet: 'green',
  unknown_object: 'default',
};

const labelColor = (l: string) => LABEL_COLORS[l] || 'default';

const fmtTs = (ts: string | null | undefined) => {
  if (!ts) return '—';
  try {
    return new Date(ts).toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return ts;
  }
};

interface DetectionRow {
  id: string;
  drone_id: string | null;
  mission_id: string | null;
  label: string;
  confidence: number;
  bbox: number[] | null;
  stream_key: string | null;
  model_tag: string | null;
  runtime: string | null;
  status: string;
  created_at: string | null;
}

interface ListDetectionsResult {
  count: number;
  detections: DetectionRow[];
  reason?: string;
}

interface DetectionStatsResult {
  since_minutes: number;
  total: number;
  by_label: Record<string, number>;
  top_label: string | null;
  reason?: string;
}

export interface VisionToolResultProps {
  name: 'list_detections' | 'detection_stats' | string;
  result: any;
}

/**
 * Render a vision tool's result inline in the assistant bubble.
 * Returns null when the result doesn't match a known vision schema,
 * so the caller can fall back to its generic renderer.
 */
export default function VisionToolResult({
  name,
  result,
}: VisionToolResultProps): React.ReactElement | null {
  if (!result || typeof result !== 'object') return null;

  if (name === 'list_detections') {
    return <ListDetectionsView data={result as ListDetectionsResult} />;
  }
  if (name === 'detection_stats') {
    return <DetectionStatsView data={result as DetectionStatsResult} />;
  }
  return null;
}

// ---------------------------------------------------------------------------
// list_detections view
// ---------------------------------------------------------------------------
function ListDetectionsView({ data }: { data: ListDetectionsResult }) {
  const rows = data.detections || [];
  const empty = rows.length === 0;
  return (
    <div
      style={{
        marginTop: 6,
        padding: 8,
        background: '#fafafa',
        border: '1px solid #f0f0f0',
        borderRadius: 6,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <EyeOutlined style={{ color: '#1677ff' }} />
        <Text strong style={{ fontSize: 12 }}>
          Vision AI · 检测记录
        </Text>
        <Tag color={empty ? 'default' : 'blue'} style={{ fontSize: 11 }}>
          {data.count} 条
        </Tag>
        {data.reason && (
          <Tag color="warning" style={{ fontSize: 11 }}>
            {data.reason}
          </Tag>
        )}
      </div>
      {empty ? (
        <Text type="secondary" style={{ fontSize: 12 }}>
          未检索到匹配的检测记录。
        </Text>
      ) : (
        <div style={{ marginTop: 6 }}>
          {rows.slice(0, 8).map((r) => (
            <DetectionRowView key={r.id} row={r} />
          ))}
          {rows.length > 8 && (
            <Text type="secondary" style={{ fontSize: 11 }}>
              …其余 {rows.length - 8} 条已省略
            </Text>
          )}
        </div>
      )}
    </div>
  );
}

function DetectionRowView({ row }: { row: DetectionRow }) {
  const conf = (row.confidence * 100).toFixed(1);
  const confColor =
    row.confidence >= 0.85
      ? 'success'
      : row.confidence >= 0.7
        ? 'processing'
        : 'default';
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        fontSize: 12,
        lineHeight: 1.8,
      }}
    >
      <Tag color={labelColor(row.label)} style={{ fontSize: 11, margin: 0 }}>
        {row.label}
      </Tag>
      <Tag color={confColor} style={{ fontSize: 11, margin: 0 }}>
        {conf}%
      </Tag>
      {row.model_tag && (
        <Text type="secondary" style={{ fontSize: 11 }}>
          {row.model_tag}
        </Text>
      )}
      {row.status && row.status !== 'new' && (
        <Tag style={{ fontSize: 11, margin: 0 }}>{row.status}</Tag>
      )}
      <Text
        type="secondary"
        style={{ fontSize: 11, marginLeft: 'auto', whiteSpace: 'nowrap' }}
      >
        <ClockCircleOutlined /> {fmtTs(row.created_at)}
      </Text>
    </div>
  );
}

// ---------------------------------------------------------------------------
// detection_stats view
// ---------------------------------------------------------------------------
function DetectionStatsView({ data }: { data: DetectionStatsResult }) {
  const buckets = Object.entries(data.by_label || {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8);
  const total = data.total || 0;
  return (
    <div
      style={{
        marginTop: 6,
        padding: 8,
        background: '#fafafa',
        border: '1px solid #f0f0f0',
        borderRadius: 6,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <BarChartOutlined style={{ color: '#722ed1' }} />
        <Text strong style={{ fontSize: 12 }}>
          Vision AI · 近 {data.since_minutes} 分钟统计
        </Text>
      </div>
      {data.reason ? (
        <Text type="warning" style={{ fontSize: 12 }}>
          {data.reason}
        </Text>
      ) : total === 0 ? (
        <Text type="secondary" style={{ fontSize: 12 }}>
          该时间窗内无检测记录。
        </Text>
      ) : (
        <>
          <Space size="large" style={{ marginTop: 4 }}>
            <Statistic
              title={<Text style={{ fontSize: 11 }}>总数</Text>}
              value={total}
              valueStyle={{ fontSize: 18 }}
            />
            {data.top_label && (
              <div>
                <div style={{ fontSize: 11, color: '#8c8c8c' }}>Top 标签</div>
                <Tag
                  color={labelColor(data.top_label)}
                  style={{ marginTop: 4, fontSize: 12 }}
                >
                  {data.top_label}
                </Tag>
              </div>
            )}
          </Space>
          {buckets.length > 0 && (
            <>
              <Divider style={{ margin: '6px 0' }} />
              <Space wrap size={[6, 6]}>
                {buckets.map(([label, n]) => (
                  <Tag key={label} color={labelColor(label)} style={{ fontSize: 11 }}>
                    {label} · {n}
                  </Tag>
                ))}
              </Space>
            </>
          )}
        </>
      )}
    </div>
  );
}
