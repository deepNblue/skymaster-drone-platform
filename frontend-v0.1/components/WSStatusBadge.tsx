'use client';

/**
 * WSStatusBadge — v2.0 UX polish.
 *
 * Displays live WebSocket connection state and stats as a small
 * badge in the corner of the map view. Feeds off `subscribeTelemetry`'s
 * `onState()` callback (added in R7).
 *
 * States: connecting (yellow) · open (green) · reconnecting (orange) · closed (grey)
 */
import React, { useEffect, useState } from 'react';
import { Space, Tag, Tooltip } from 'antd';
import {
  LinkOutlined, WarningOutlined, DisconnectOutlined,
  LoadingOutlined,
} from '@ant-design/icons';
import type { WsState, WsSubscription } from '@/lib/ws';

interface Props {
  subscription?: WsSubscription | null;
  droneId?: string;
}

const CONFIG: Record<
  WsState, { color: string; icon: React.ReactNode; label: string }
> = {
  connecting: {
    color: 'gold',
    icon: <LoadingOutlined />,
    label: '连接中',
  },
  open: {
    color: 'green',
    icon: <LinkOutlined />,
    label: '在线',
  },
  reconnecting: {
    color: 'orange',
    icon: <WarningOutlined />,
    label: '重连中',
  },
  closed: {
    color: 'default',
    icon: <DisconnectOutlined />,
    label: '已断开',
  },
};

export default function WSStatusBadge({ subscription, droneId }: Props) {
  const [state, setState] = useState<WsState>('closed');

  useEffect(() => {
    if (!subscription) return;
    return subscription.onState(setState);
  }, [subscription]);

  const cfg = CONFIG[state] ?? CONFIG.closed;
  const tooltip = droneId
    ? `WebSocket · drone ${droneId} · ${cfg.label}`
    : `WebSocket · ${cfg.label}`;

  return (
    <Tooltip title={tooltip}>
      <Tag icon={cfg.icon} color={cfg.color} style={{ fontSize: 12 }}>
        {cfg.label}
      </Tag>
    </Tooltip>
  );
}
