'use client';

/**
 * Video Wall — 9-grid multi-video monitoring page (对标大疆司空 2 多路视频).
 *
 * Layouts: 1 / 4 / 9 tiles. Each tile shows drone SN, online status and
 * stream metadata (resolution / fps / codec / bitrate), with live telemetry
 * and an AI-vision detection badge. Click a tile to enlarge it in a modal.
 *
 * Data sources (all degrade independently):
 *   - GET /drones/stats          fleet roster
 *   - GET /video-streams         DB stream registry (bitrate / res ...)
 *   - GET /streams               MediaMTX live paths
 *   - WS  /ws/telemetry/{id}     live battery / speed / mode
 *   - WS  /ws/vision             global AI detection frames
 *
 * When neither the registry nor MediaMTX can supply a playback URL, tiles
 * show a "无视频信号" placeholder with reconnect + custom-URL controls.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Button,
  ConfigProvider,
  Segmented,
  Space,
  Tag,
  Tooltip,
  theme as antdTheme,
} from 'antd';
import {
  AppstoreOutlined,
  BorderOutlined,
  EyeOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import VideoTile, { VideoTileTelemetry } from '@/components/video-wall/VideoTile';
import { EmptySlot } from '@/components/video-wall/VideoTile';
import { useVideoWallData } from '@/lib/videoWall';
import { subscribeTelemetry, TelemetryPayload } from '@/lib/ws';
import { useVisionStream, VisionFrameEvent } from '@/lib/useVisionStream';

const DARK_BG = '#0b1220';
const PANEL_BG = '#111a2c';
const ACCENT = '#2b7fff';
const GREEN = '#52c41a';

type LayoutSize = 1 | 4 | 9;

export default function VideoWallPage() {
  const { tiles, loading, refreshTick, refresh, setCustomUrl } =
    useVideoWallData(10_000);
  const [layout, setLayout] = useState<LayoutSize>(9);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [clock, setClock] = useState('--:--:--');
  const [telemetry, setTelemetry] = useState<
    Record<string, VideoTileTelemetry>
  >({});
  const [wsActive, setWsActive] = useState(0);

  const vision = useVisionStream(); // global fleet-wide vision stream

  // ---- Telemetry subscriptions (one per drone, stable across polls) ----
  const subsRef = useRef<Map<string, ReturnType<typeof subscribeTelemetry>>>(new Map());
  useEffect(() => {
    const desired = new Set(tiles.map((t) => t.drone.drone_id));
    // Close subs for drones that disappeared.
    for (const [id, sub] of Array.from(subsRef.current.entries())) {
      if (!desired.has(id)) {
        sub.close();
        subsRef.current.delete(id);
      }
    }
    // Open subs for new drones.
    for (const id of desired) {
      if (subsRef.current.has(id)) continue;
      const sub = subscribeTelemetry(id, (msg: TelemetryPayload) => {
        setWsActive((n) => n + 1);
        setTelemetry((prev) => ({
          ...prev,
          [id]: {
            battery:
              typeof msg.battery === 'number' ? msg.battery : prev[id]?.battery,
            speed:
              typeof msg.speed === 'number' ? msg.speed : prev[id]?.speed,
            alt: typeof msg.alt === 'number' ? msg.alt : prev[id]?.alt,
            mode: (msg.mode as string) || prev[id]?.mode,
          },
        }));
      });
      subsRef.current.set(id, sub);
    }
    // NOTE: no per-effect cleanup — the diff above reconciles. The unmount
    // effect below closes all sockets.
  }, [tiles]);

  // Close all telemetry sockets on unmount only.
  useEffect(() => {
    return () => {
      subsRef.current.forEach((s) => s.close());
      subsRef.current.clear();
    };
  }, []);

  // ---- Clock ----
  useEffect(() => {
    const tick = () =>
      setClock(new Date().toLocaleTimeString('zh-CN', { hour12: false }));
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, []);

  // Reset ws rate counter every 5s.
  useEffect(() => {
    const t = setInterval(() => setWsActive(0), 5000);
    return () => clearInterval(t);
  }, []);

  // ---- Per-drone vision counts from the rolling frame buffer ----
  const visionCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const f of vision.frames as VisionFrameEvent[]) {
      if (f.drone_id) counts[f.drone_id] = (counts[f.drone_id] ?? 0) + 1;
    }
    return counts;
  }, [vision.frames]);

  const totalDetections = useMemo(
    () => Object.values(visionCounts).reduce((a, b) => a + b, 0),
    [visionCounts],
  );

  const onlineCount = tiles.filter((t) => t.drone.online).length;
  const liveCount = tiles.filter((t) => t.hlsUrl).length;

  // ---- Select which tiles fill the grid for the current layout ----
  const visibleTiles = useMemo(() => {
    if (tiles.length === 0) return [];
    if (layout === 1) {
      const focused =
        tiles.find((t) => t.drone.drone_id === focusedId) ??
        tiles.find((t) => t.drone.online) ??
        tiles[0];
      return [focused];
    }
    return tiles.slice(0, layout);
  }, [tiles, layout, focusedId]);

  const slots = layout; // 1/4/9
  const cols = layout === 1 ? 1 : layout === 4 ? 2 : 3;
  const rows = layout === 1 ? 1 : layout === 4 ? 2 : 3;

  const expandedTile =
    tiles.find((t) => t.drone.drone_id === expandedId) ?? null;

  const focusedIndex = tiles.findIndex(
    (t) => t.drone.drone_id === (focusedId ?? visibleTiles[0]?.drone.drone_id),
  );

  const cycleFocus = (delta: number) => {
    if (tiles.length === 0) return;
    const idx = focusedIndex < 0 ? 0 : focusedIndex;
    const next = (idx + delta + tiles.length) % tiles.length;
    setFocusedId(tiles[next].drone.drone_id);
  };

  return (
    <ConfigProvider
      theme={{
        algorithm: antdTheme.darkAlgorithm,
        token: {
          colorPrimary: ACCENT,
          colorBgContainer: PANEL_BG,
          borderRadius: 8,
        },
      }}
    >
      <div
        style={{
          minHeight: 'calc(100vh - 56px)',
          background: DARK_BG,
          margin: -24,
          padding: 0,
          color: '#e6f0ff',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* ===== Toolbar ===== */}
        <div
          style={{
            height: 52,
            flexShrink: 0,
            background: 'linear-gradient(90deg, #0d1526 0%, #101d38 100%)',
            borderBottom: '1px solid #1e2c4a',
            display: 'flex',
            alignItems: 'center',
            gap: 18,
            padding: '0 18px',
            fontSize: 13,
          }}
        >
          <span style={{ fontWeight: 700, fontSize: 15, letterSpacing: 1 }}>
            <AppstoreOutlined style={{ color: ACCENT }} /> 视频九宫格{' '}
            <span style={{ color: '#6f86b0', fontWeight: 400 }}>VIDEO WALL</span>
          </span>

          <Segmented
            size="small"
            value={layout}
            onChange={(v) => setLayout(v as LayoutSize)}
            options={[
              { label: '1', value: 1, icon: <BorderOutlined /> },
              { label: '4', value: 4, icon: <BorderOutlined /> },
              { label: '9', value: 9, icon: <AppstoreOutlined /> },
            ]}
          />

          {layout === 1 && tiles.length > 1 && (
            <Space size={4}>
              <Button size="small" onClick={() => cycleFocus(-1)}>
                ‹ 上一路
              </Button>
              <Button size="small" onClick={() => cycleFocus(1)}>
                下一路 ›
              </Button>
            </Space>
          )}

          <span style={{ marginLeft: 8 }}>
            <ThunderboltOutlined style={{ color: GREEN }} /> 在线{' '}
            <b style={{ color: GREEN }}>
              {onlineCount}/{tiles.length}
            </b>
          </span>
          <span>
            码流 <b style={{ color: liveCount ? ACCENT : '#666' }}>{liveCount}</b>
          </span>
          <Tooltip title="最近 5 秒遥测消息数">
            <span style={{ color: wsActive > 0 ? GREEN : '#666' }}>
              遥测流 <b>{wsActive}/5s</b>
            </span>
          </Tooltip>
          {totalDetections > 0 && (
            <span style={{ color: '#ff7875' }}>
              <EyeOutlined /> AI 检测 <b>{totalDetections}</b>
            </span>
          )}
          {vision.connected && (
            <Tag color="blue" style={{ marginLeft: 0, fontSize: 10 }}>
              VISION WS
            </Tag>
          )}

          <span style={{ marginLeft: 'auto', display: 'flex', gap: 12, alignItems: 'center' }}>
            <Tooltip title="重新拉取机队与码流列表">
              <Button
                size="small"
                icon={<ReloadOutlined spin={loading} />}
                onClick={refresh}
              >
                刷新
              </Button>
            </Tooltip>
            <span style={{ fontFamily: 'monospace', color: '#9fb8e0' }}>
              {clock}
            </span>
          </span>
        </div>

        {/* ===== Grid ===== */}
        <div
          style={{
            flex: 1,
            minHeight: 0,
            padding: 10,
            display: 'grid',
            gridTemplateColumns: `repeat(${cols}, 1fr)`,
            gridTemplateRows: `repeat(${rows}, 1fr)`,
            gap: 8,
          }}
        >
          {visibleTiles.map((tile) => (
            <div key={tile.drone.drone_id} style={{ minHeight: 0, minWidth: 0 }}>
              <VideoTile
                tile={tile}
                telemetry={telemetry[tile.drone.drone_id]}
                visionCount={visionCounts[tile.drone.drone_id] ?? 0}
                onExpand={() => {
                  setFocusedId(tile.drone.drone_id);
                  setExpandedId(tile.drone.drone_id);
                }}
                onCustomUrlChange={(url) =>
                  setCustomUrl(tile.drone.drone_id, url)
                }
                onRefresh={refresh}
              />
            </div>
          ))}
          {Array.from({ length: Math.max(0, slots - visibleTiles.length) }).map(
            (_, i) => (
              <div key={`empty-${i}`} style={{ minHeight: 0, minWidth: 0 }}>
                <EmptySlot />
              </div>
            ),
          )}
        </div>
      </div>

      {/* ===== Expanded single-tile modal ===== */}
      {expandedTile && (
        <ConfigProvider
          theme={{
            algorithm: antdTheme.darkAlgorithm,
            token: { colorPrimary: ACCENT, colorBgContainer: PANEL_BG },
          }}
        >
          <div
            style={{
              position: 'fixed',
              inset: 0,
              background: 'rgba(5,9,16,0.92)',
              zIndex: 1000,
              display: 'flex',
              flexDirection: 'column',
              padding: 24,
            }}
            onClick={() => setExpandedId(null)}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                marginBottom: 12,
                color: '#e6f0ff',
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <span style={{ fontFamily: 'monospace', fontSize: 16, fontWeight: 600 }}>
                {expandedTile.drone.sn}
              </span>
              <Tag color={expandedTile.drone.online ? 'green' : 'default'}>
                {expandedTile.drone.online ? '在线' : '离线'}
              </Tag>
              <span style={{ flex: 1 }} />
              <Button onClick={() => setExpandedId(null)}>关闭 ✕</Button>
            </div>
            <div
              style={{ flex: 1, minHeight: 0 }}
              onClick={(e) => e.stopPropagation()}
            >
              <VideoTile
                tile={expandedTile}
                telemetry={telemetry[expandedTile.drone.drone_id]}
                visionCount={visionCounts[expandedTile.drone.drone_id] ?? 0}
                onExpand={() => setExpandedId(null)}
                onCustomUrlChange={(url) =>
                  setCustomUrl(expandedTile.drone.drone_id, url)
                }
                onRefresh={refresh}
                large
              />
            </div>
          </div>
        </ConfigProvider>
      )}
    </ConfigProvider>
  );
}
