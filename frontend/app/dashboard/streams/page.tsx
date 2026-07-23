'use client';

import React, { useEffect, useRef, useState } from 'react';
import { Card, Button, Space, Typography, message, Empty, Spin } from 'antd';
import {
  PlayCircleOutlined,
  PauseCircleOutlined,
  CameraOutlined,
  FullscreenOutlined,
} from '@ant-design/icons';
import Link from 'next/link';
import { getStreams } from '@/lib/api';

const { Title, Text } = Typography;

interface StreamItem {
  id: string;
  drone_id?: string;
  drone_sn?: string;
  sn?: string;
  hls_url?: string;
  status?: string;
}

interface HlsPlayerProps {
  src: string;
  playing: boolean;
  onSnapshot: (video: HTMLVideoElement | null) => void;
  videoRef: React.RefObject<HTMLVideoElement>;
}

function HlsVideo({ src, playing, videoRef }: HlsPlayerProps) {
  const [nativeOk, setNativeOk] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    let hls: any = null;
    const video = videoRef.current;
    if (!video) return;

    const canNative = video.canPlayType('application/vnd.apple.mpegurl') !== '';
    setNativeOk(canNative);

    if (canNative) {
      video.src = src;
    } else {
      // Dynamic import of hls.js — optional peer dependency.
      import('hls.js')
        .then((mod) => {
          if (cancelled) return;
          const Hls = mod.default;
          if (Hls && Hls.isSupported()) {
            hls = new Hls();
            hls.loadSource(src);
            hls.attachMedia(video);
          } else {
            video.src = src;
          }
        })
        .catch(() => {
          if (!cancelled) video.src = src;
        });
    }

    return () => {
      cancelled = true;
      if (hls) {
        try {
          hls.destroy();
        } catch {
          /* noop */
        }
      }
      if (video) video.src = '';
    };
  }, [src, videoRef]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    if (playing) {
      video.play().catch(() => {
        /* autoplay may be blocked */
      });
    } else {
      video.pause();
    }
  }, [playing, videoRef]);

  return (
    <video
      ref={videoRef}
      style={{ width: '100%', height: '100%', background: '#000', objectFit: 'cover' }}
      muted
      playsInline
      controls={false}
    />
  );
}

function StreamCell({ stream }: { stream: StreamItem }) {
  const [playing, setPlaying] = useState(true);
  const videoRef = useRef<HTMLVideoElement>(null);
  const sn = stream.drone_sn || stream.sn || stream.drone_id || stream.id;
  const src =
    stream.hls_url ||
    `/api/v1/streams/${encodeURIComponent(stream.id)}/hls`;

  const takeSnapshot = () => {
    const video = videoRef.current;
    if (!video || !video.videoWidth) {
      message.warning('视频未就绪，无法截图');
      return;
    }
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.drawImage(video, 0, 0);
    canvas.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `snapshot-${sn}-${Date.now()}.png`;
      a.click();
      URL.revokeObjectURL(url);
    });
  };

  return (
    <Card
      size="small"
      bodyStyle={{ padding: 0 }}
      title={
        <Space>
          <Text strong style={{ color: 'var(--sm-text-primary)' }}>
            {sn}
          </Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {stream.status || 'live'}
          </Text>
        </Space>
      }
      extra={
        <Link href={`/dashboard/streams/${encodeURIComponent(stream.drone_id || stream.id)}`}>
          <Button type="link" size="small" icon={<FullscreenOutlined />}>
            全屏
          </Button>
        </Link>
      }
    >
      <div style={{ position: 'relative', paddingTop: '56.25%', background: '#000' }}>
        <div style={{ position: 'absolute', inset: 0 }}>
          <HlsVideo
            src={src}
            playing={playing}
            onSnapshot={() => {}}
            videoRef={videoRef}
          />
        </div>
      </div>
      <div style={{ padding: 8, display: 'flex', justifyContent: 'space-between' }}>
        <Space>
          <Button
            size="small"
            icon={playing ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
            onClick={() => setPlaying((p) => !p)}
          >
            {playing ? '暂停' : '播放'}
          </Button>
          <Button size="small" icon={<CameraOutlined />} onClick={takeSnapshot}>
            截图
          </Button>
        </Space>
        <Text type="secondary" style={{ fontSize: 12 }}>
          HLS
        </Text>
      </div>
    </Card>
  );
}

export default function StreamsPage() {
  const [streams, setStreams] = useState<StreamItem[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let mounted = true;
    (async () => {
      setLoading(true);
      try {
        const list = await getStreams();
        const arr = Array.isArray(list) ? list : list?.items || [];
        if (mounted) setStreams(arr);
      } catch (err: any) {
        message.error(err?.message || '加载视频流列表失败');
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  const count = streams.length;
  const cols = count <= 1 ? 1 : count <= 4 ? 2 : 3;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={3} style={{ color: 'var(--sm-text-primary)', margin: 0 }}>
          视频墙
        </Title>
        <Text type="secondary">当前在线：{count}</Text>
      </div>

      {loading && (
        <div style={{ padding: 40, textAlign: 'center' }}>
          <Spin />
        </div>
      )}

      {!loading && count === 0 && <Empty description="暂无视频流" />}

      {!loading && count > 0 && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: `repeat(${cols}, 1fr)`,
            gap: 16,
          }}
        >
          {streams.map((s) => (
            <StreamCell key={s.id} stream={s} />
          ))}
        </div>
      )}
    </div>
  );
}
