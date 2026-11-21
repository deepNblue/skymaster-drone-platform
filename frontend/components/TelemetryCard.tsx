'use client';

import React, { useEffect, useState } from 'react';
import { Card, Descriptions, Spin, Alert, Tag } from 'antd';
import { subscribeTelemetry, TelemetryPayload } from '@/lib/ws';

export interface TelemetryCardProps {
  droneId: string;
  title?: string;
}

export default function TelemetryCard({ droneId, title }: TelemetryCardProps) {
  const [data, setData] = useState<TelemetryPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setData(null);
    setError(null);
    setLoading(true);

    let timeoutId: ReturnType<typeof setTimeout> | null = setTimeout(() => {
      if (!data) setError('未收到遥测数据');
      setLoading(false);
    }, 5000);

    const sub = subscribeTelemetry(droneId, (payload) => {
      setData(payload);
      setLoading(false);
      setError(null);
      if (timeoutId) {
        clearTimeout(timeoutId);
        timeoutId = null;
      }
    });

    return () => {
      if (timeoutId) clearTimeout(timeoutId);
      sub.close();
    };

  }, [droneId]);

  return (
    <Card size="small" title={title || `遥测 · ${droneId}`}>
      {loading && !data && <Spin size="small" />}
      {error && !data && <Alert type="warning" showIcon message={error} />}
      {data && (
        <Descriptions column={1} size="small">
          <Descriptions.Item label="纬度">
            {data.lat != null ? Number(data.lat).toFixed(6) : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="经度">
            {data.lng != null ? Number(data.lng).toFixed(6) : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="高度">
            {data.alt != null ? `${Number(data.alt).toFixed(1)} m` : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="速度">
            {data.speed != null ? `${Number(data.speed).toFixed(1)} m/s` : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="电量">
            {data.battery != null ? (
              <Tag
                color={
                  Number(data.battery) < 20
                    ? 'red'
                    : Number(data.battery) < 50
                      ? 'gold'
                      : 'green'
                }
              >
                {Number(data.battery).toFixed(0)}%
              </Tag>
            ) : (
              '-'
            )}
          </Descriptions.Item>
          <Descriptions.Item label="模式">
            {data.mode ? <Tag>{data.mode}</Tag> : '-'}
          </Descriptions.Item>
        </Descriptions>
      )}
    </Card>
  );
}
