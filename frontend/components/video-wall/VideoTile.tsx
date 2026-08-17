'use client';

/**
 * VideoTile — a single cell on the video wall.
 *
 * Shows the HLS feed when a URL can be resolved, otherwise a "no signal"
 * placeholder with reconnect + custom-URL controls. Overlays carry:
 *   - drone SN + online dot + LIVE badge
 *   - resolution / fps / codec / bitrate / source
 *   - AI vision detection count (from the global vision WS)
 *   - live telemetry (battery / speed / mode)
 */
import { useEffect, useRef, useState } from 'react';
import { Button, Dropdown, Input, Modal, Tooltip, message } from 'antd';
import type { MenuProps } from 'antd';
import {
  ApiOutlined,
  ExpandOutlined,
  EyeOutlined,
  LinkOutlined,
  ReloadOutlined,
  SettingOutlined,
  VideoCameraAddOutlined,
} from '@ant-design/icons';
import HlsPlayer, { PlayerState } from './HlsPlayer';
import type { TileSource } from '@/lib/videoWall';

const GREEN = '#52c41a';
const AMBER = '#faad14';
const RED = '#ff4d4f';
const ACCENT = '#2b7fff';
const MUTED = '#8ca3c7';

export interface VideoTileTelemetry {
  battery?: number;
  speed?: number;
  alt?: number;
  mode?: string;
}

export interface VideoTileProps {
  tile: TileSource;
  telemetry?: VideoTileTelemetry;
  /** Number of recent AI detections for this drone. */
  visionCount: number;
  onExpand: () => void;
  onCustomUrlChange: (url: string | null) => void;
  /** Called after a manual reconnect (so the page can re-poll sources). */
  onRefresh?: () => void;
  /** Larger UI chrome for the single-pane / modal view. */
  large?: boolean;
}

const SOURCE_LABEL: Record<TileSource['source'], string> = {
  registry: 'REGISTRY',
  mediamtx: 'MEDIAMTX',
  custom: 'CUSTOM',
  none: 'NO FEED',
};

function formatBitrate(kbps: number | null | undefined): string {
  if (!kbps || kbps <= 0) return '-- kbps';
  if (kbps >= 1000) return `${(kbps / 1000).toFixed(1)} Mbps`;
  return `${kbps} kbps`;
}

export default function VideoTile({
  tile,
  telemetry,
  visionCount,
  onExpand,
  onCustomUrlChange,
  onRefresh,
  large = false,
}: VideoTileProps) {
  const [playerState, setPlayerState] = useState<PlayerState>('idle');
  const [retryKey, setRetryKey] = useState(0);
  const [urlModal, setUrlModal] = useState(false);
  const [urlDraft, setUrlDraft] = useState('');
  const [liveTimer, setLiveTimer] = useState(0);
  const liveStartedRef = useRef<number | null>(null);

  const { drone, registry, mediamtx, hlsUrl, source } = tile;
  const online = drone.online;
  const width = registry?.width ?? null;
  const height = registry?.height ?? null;
  const fps = registry?.fps ?? null;
  const codec = registry?.codec ?? null;
  const bitrate = registry?.bitrate_kbps ?? null;
  const streamActive =
    registry?.status === 'active' || mediamtx?.ready === true || source === 'custom';

  // Reset player state when the URL identity changes.
  useEffect(() => {
    setPlayerState(hlsUrl ? 'loading' : 'idle');
    liveStartedRef.current = null;
    setLiveTimer(0);
  }, [hlsUrl, retryKey]);

  // Live "uptime" timer once playing.
  useEffect(() => {
    if (playerState !== 'playing') {
      liveStartedRef.current = null;
      setLiveTimer(0);
      return;
    }
    if (liveStartedRef.current === null) liveStartedRef.current = Date.now();
    const t = setInterval(() => {
      if (liveStartedRef.current) {
        setLiveTimer(Math.floor((Date.now() - liveStartedRef.current) / 1000));
      }
    }, 1000);
    return () => clearInterval(t);
  }, [playerState]);

  const handleReconnect = () => {
    setRetryKey((k) => k + 1);
    onRefresh?.();
  };

  const openUrlModal = () => {
    setUrlDraft(tile.customUrl ?? hlsUrl ?? '');
    setUrlModal(true);
  };

  const saveUrl = () => {
    const v = urlDraft.trim();
    onCustomUrlChange(v || null);
    setUrlModal(false);
    message.success(v ? '已应用自定义流地址' : '已清除自定义流地址');
    setRetryKey((k) => k + 1);
  };

  const menu: MenuProps['items'] = [
    {
      key: 'expand',
      icon: <ExpandOutlined />,
      label: '单格放大',
      onClick: onExpand,
    },
    {
      key: 'url',
      icon: <LinkOutlined />,
      label: '自定义流地址',
      onClick: openUrlModal,
    },
    { type: 'divider' },
    {
      key: 'reconnect',
      icon: <ReloadOutlined />,
      label: '重连',
      onClick: handleReconnect,
    },
  ];

  if (tile.customUrl) {
    menu!.splice(2, 0, {
      key: 'clear-url',
      icon: <LinkOutlined />,
      label: '清除自定义地址',
      onClick: () => {
        onCustomUrlChange(null);
        message.info('已清除自定义流地址');
      },
    });
  }

  const showPlaceholder = !hlsUrl || playerState === 'error';
  const resolution =
    width && height ? `${width}×${height}` : mediamtx ? 'LIVE' : '--';
  const batteryColor =
    (telemetry?.battery ?? 0) > 50
      ? GREEN
      : (telemetry?.battery ?? 0) > 25
        ? AMBER
        : RED;

  return (
    <div
      style={{
        position: 'relative',
        width: '100%',
        height: '100%',
        background: '#000',
        borderRadius: large ? 10 : 8,
        overflow: 'hidden',
        border: `1px solid ${source === 'custom' ? ACCENT : '#1e2c4a'}`,
        cursor: showPlaceholder ? 'default' : 'pointer',
      }}
      onClick={() => {
        if (!showPlaceholder) onExpand();
      }}
    >
      {/* ---- Video / placeholder ---- */}
      {hlsUrl && !showPlaceholder ? (
        <HlsPlayer
          src={hlsUrl}
          retryKey={retryKey}
          onStateChange={setPlayerState}
          style={{ width: '100%', height: '100%', objectFit: 'contain', background: '#000' }}
        />
      ) : (
        <NoSignalPlaceholder
          online={online}
          hasUrl={!!hlsUrl}
          onReconnect={handleReconnect}
          onSetUrl={openUrlModal}
          large={large}
        />
      )}

      {/* ---- Top overlay ---- */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          padding: large ? '10px 12px' : '6px 8px',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          background:
            'linear-gradient(180deg, rgba(0,0,0,0.75) 0%, rgba(0,0,0,0) 100%)',
          fontSize: large ? 13 : 11.5,
          zIndex: 2,
        }}
      >
        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: online ? GREEN : '#4a5568',
            boxShadow: online ? `0 0 6px ${GREEN}` : 'none',
            flexShrink: 0,
          }}
        />
        <span
          style={{
            fontFamily: 'monospace',
            color: '#e6f0ff',
            fontWeight: 600,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
          title={drone.sn}
        >
          {drone.sn}
        </span>
        {streamActive && playerState === 'playing' && (
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              background: 'rgba(255,77,79,0.18)',
              color: RED,
              border: `1px solid ${RED}`,
              borderRadius: 4,
              padding: '1px 6px',
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: 0.5,
            }}
          >
            <span
              style={{
                width: 5,
                height: 5,
                borderRadius: '50%',
                background: RED,
                animation: 'vwpulse 1.2s infinite',
              }}
            />
            LIVE
          </span>
        )}
        <span style={{ flex: 1 }} />
        <span
          style={{
            fontFamily: 'monospace',
            color: MUTED,
            fontSize: 10,
            background: 'rgba(0,0,0,0.45)',
            padding: '1px 6px',
            borderRadius: 4,
          }}
        >
          {SOURCE_LABEL[source]}
        </span>
        <Dropdown menu={{ items: menu }} trigger={['click']} placement="bottomRight">
          <Button
            type="text"
            size="small"
            icon={<SettingOutlined style={{ color: '#c6d6f2' }} />}
            onClick={(e) => e.stopPropagation()}
            style={{ padding: '0 4px', height: 22 }}
          />
        </Dropdown>
      </div>

      {/* ---- AI detection badge (top-right under settings) ---- */}
      {visionCount > 0 && (
        <Tooltip title={`最近检测到 ${visionCount} 个目标`}>
          <div
            style={{
              position: 'absolute',
              top: large ? 44 : 32,
              right: large ? 12 : 8,
              display: 'flex',
              alignItems: 'center',
              gap: 4,
              background: 'rgba(255,77,79,0.18)',
              border: `1px solid ${RED}`,
              color: '#ffccc7',
              borderRadius: 12,
              padding: '2px 8px',
              fontSize: 11,
              fontWeight: 600,
              zIndex: 2,
            }}
          >
            <EyeOutlined /> AI {visionCount}
          </div>
        </Tooltip>
      )}

      {/* ---- Bottom overlay ---- */}
      <div
        style={{
          position: 'absolute',
          bottom: 0,
          left: 0,
          right: 0,
          padding: large ? '8px 12px' : '5px 8px',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          background:
            'linear-gradient(0deg, rgba(0,0,0,0.8) 0%, rgba(0,0,0,0) 100%)',
          fontSize: large ? 12 : 10.5,
          fontFamily: 'monospace',
          color: MUTED,
          zIndex: 2,
        }}
      >
        <span>{resolution}</span>
        {fps != null && <span>{fps}fps</span>}
        {codec && <span>{codec.toUpperCase()}</span>}
        <span>{formatBitrate(bitrate)}</span>
        <span style={{ flex: 1 }} />
        {playerState === 'playing' && liveTimer > 0 && (
          <span style={{ color: '#c6d6f2' }}>
            <ApiOutlined /> {Math.floor(liveTimer / 60)}:
            {String(liveTimer % 60).padStart(2, '0')}
          </span>
        )}
        {typeof telemetry?.battery === 'number' && (
          <span style={{ color: batteryColor, fontWeight: 700 }}>
            {telemetry.battery.toFixed(0)}%
          </span>
        )}
        {typeof telemetry?.speed === 'number' && (
          <span style={{ color: '#13c2c2' }}>{telemetry.speed.toFixed(0)}m/s</span>
        )}
      </div>

      {/* ---- Loading spinner over video ---- */}
      {hlsUrl && playerState === 'loading' && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'rgba(0,0,0,0.35)',
            zIndex: 1,
          }}
        >
          <div
            style={{
              width: large ? 36 : 26,
              height: large ? 36 : 26,
              border: '3px solid rgba(43,127,255,0.25)',
              borderTopColor: ACCENT,
              borderRadius: '50%',
              animation: 'vwspin 0.9s linear infinite',
            }}
          />
        </div>
      )}

      <Modal
        title="自定义流地址"
        open={urlModal}
        onOk={saveUrl}
        onCancel={() => setUrlModal(false)}
        okText="应用"
        cancelText="取消"
        width={460}
      >
        <p style={{ color: MUTED, marginBottom: 8, fontSize: 12 }}>
          输入 HLS（.m3u8）地址，该地址仅保存在本浏览器中，用于在 MediaMTX / 流注册表不可用时手动指定码流。
        </p>
        <Input
          placeholder="https://example.com/live/stream.m3u8"
          value={urlDraft}
          onChange={(e) => setUrlDraft(e.target.value)}
          onPressEnter={saveUrl}
          prefix={<LinkOutlined />}
        />
      </Modal>

      {/* keyframes via a style tag — once per tile is cheap and scoped */}
      <style>{`
        @keyframes vwspin { to { transform: rotate(360deg); } }
        @keyframes vwpulse { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }
      `}</style>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Empty slot (no drone assigned to this grid position)
// ---------------------------------------------------------------------------

export function EmptySlot() {
  return (
    <div
      style={{
        position: 'relative',
        width: '100%',
        height: '100%',
        background:
          'repeating-linear-gradient(45deg, #0c1322 0 12px, #0a1018 12px 24px)',
        border: '1px dashed #1e2c4a',
        borderRadius: 8,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: '#4a5a78',
        fontSize: 12,
        letterSpacing: 1,
      }}
    >
      空闲机位
    </div>
  );
}

// ---------------------------------------------------------------------------
// No-signal placeholder
// ---------------------------------------------------------------------------

function NoSignalPlaceholder({
  online,
  hasUrl,
  onReconnect,
  onSetUrl,
  large,
}: {
  online: boolean;
  hasUrl: boolean;
  onReconnect: () => void;
  onSetUrl: () => void;
  large: boolean;
}) {
  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: large ? 14 : 10,
        background:
          'radial-gradient(circle at 50% 40%, #111a2c 0%, #070b14 100%)',
        color: MUTED,
        padding: 12,
        textAlign: 'center',
      }}
    >
      <VideoCameraAddOutlined
        style={{ fontSize: large ? 44 : 32, color: online ? '#3a4a6a' : RED }}
      />
      <div style={{ fontSize: large ? 15 : 13, fontWeight: 600, color: '#c6d6f2' }}>
        {hasUrl ? '视频信号中断' : '无视频信号'}
      </div>
      <div style={{ fontSize: 11, maxWidth: 220, lineHeight: 1.6 }}>
        {online
          ? hasUrl
            ? '码流地址已配置但无法播放，请检查 MediaMTX 网关或稍后重连。'
            : '无人机在线，但尚未注册视频码流。可手动指定 HLS 地址。'
          : '无人机离线，暂无码流。设备上线后将自动尝试拉流。'}
      </div>
      <div style={{ display: 'flex', gap: 8, marginTop: 2 }}>
        <Button
          size={large ? 'middle' : 'small'}
          icon={<ReloadOutlined />}
          onClick={(e) => {
            e.stopPropagation();
            onReconnect();
          }}
        >
          重连
        </Button>
        <Button
          size={large ? 'middle' : 'small'}
          type="primary"
          ghost
          icon={<LinkOutlined />}
          onClick={(e) => {
            e.stopPropagation();
            onSetUrl();
          }}
        >
          指定地址
        </Button>
      </div>
    </div>
  );
}
