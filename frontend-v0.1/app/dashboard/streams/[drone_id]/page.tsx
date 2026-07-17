'use client';

import React, { useEffect, useRef, useState } from 'react';
import { Row, Col, Card, Button, Space, Typography, message, Breadcrumb } from 'antd';
import {
  PlayCircleOutlined,
  PauseCircleOutlined,
  CameraOutlined,
  ArrowLeftOutlined,
} from '@ant-design/icons';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import TelemetryCard from '@/components/TelemetryCard';
import CesiumMap from '@/components/CesiumMap';

const { Title, Text } = Typography;

export default function StreamDetailPage() {
  const params = useParams();
  const router = useRouter();
  const droneId =
    (Array.isArray(params?.drone_id) ? params.drone_id[0] : params?.drone_id) || '';

  const videoRef = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(true);
  const src = `/api/v1/streams/${encodeURIComponent(droneId)}/hls`;

  useEffect(() => {
    let hls: any = null;
    const video = videoRef.current;
    if (!video || !droneId) return;

    const canNative = video.canPlayType('application/vnd.apple.mpegurl') !== '';
    if (canNative) {
      video.src = src;
    } else {
      import('hls.js')
        .then((mod) => {
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
          video.src = src;
        });
    }
    return () => {
      if (hls) {
        try {
          hls.destroy();
        } catch {
          /* noop */
        }
      }
      if (video) video.src = '';
    };
  }, [droneId, src]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    if (playing) {
      video.play().catch(() => {});
    } else {
      video.pause();
    }
  }, [playing]);

  const snapshot = () => {
    const v = videoRef.current;
    if (!v || !v.videoWidth) {
      message.warning('视频未就绪');
      return;
    }
    const canvas = document.createElement('canvas');
    canvas.width = v.videoWidth;
    canvas.height = v.videoHeight;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.drawImage(v, 0, 0);
    canvas.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `snapshot-${droneId}-${Date.now()}.png`;
      a.click();
      URL.revokeObjectURL(url);
    });
  };

  return (
    <div>
      <Breadcrumb
        style={{ marginBottom: 16 }}
        items={[
          { title: <Link href="/dashboard/streams">视频墙</Link> },
          { title: droneId },
        ]}
      />
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => router.back()}>
            返回
          </Button>
          <Title level={3} style={{ color: 'var(--sm-text-primary)', margin: 0 }}>
            视频详情 · {droneId}
          </Title>
        </Space>
      </div>

      <Row gutter={16}>
        <Col xs={24} lg={17}>
          <Card bodyStyle={{ padding: 0 }}>
            <div style={{ position: 'relative', paddingTop: '56.25%', background: '#000' }}>
              <video
                ref={videoRef}
                style={{
                  position: 'absolute',
                  inset: 0,
                  width: '100%',
                  height: '100%',
                  background: '#000',
                }}
                muted
                playsInline
                controls={false}
              />
            </div>
            <div style={{ padding: 12, display: 'flex', justifyContent: 'space-between' }}>
              <Space>
                <Button
                  icon={playing ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
                  onClick={() => setPlaying((p) => !p)}
                >
                  {playing ? '暂停' : '播放'}
                </Button>
                <Button icon={<CameraOutlined />} onClick={snapshot}>
                  截图
                </Button>
              </Space>
              <Text type="secondary">HLS · {src}</Text>
            </div>
          </Card>
          <Card title="实时位置" style={{ marginTop: 16 }} bodyStyle={{ padding: 0 }}>
            <CesiumMap droneId={droneId} height={400} />
          </Card>
        </Col>
        <Col xs={24} lg={7}>
          <TelemetryCard droneId={droneId} title="实时遥测" />
        </Col>
      </Row>
    </div>
  );
}
