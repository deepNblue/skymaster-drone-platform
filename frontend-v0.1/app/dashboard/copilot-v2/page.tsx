'use client';

/**
 * Copilot v2 dashboard page — T4.2 (T5.4 wires the map fly-to).
 *
 * Layout:
 *   ┌──────────────────────┬────────────────────────────┐
 *   │  Copilot v2 会话     │  待审批操作 (V2ApprovalsInbox)  │
 *   ├──────────────────────┴────────────────────────────┤
 *   │  3D 地球（点击助理里的检测行会自动 flyTo 到目标）    │
 *   └──────────────────────────────────────────────────┘
 */
import React, { useCallback, useRef, useState } from 'react';
import { Row, Col, Card, Button, Space, Typography, Alert, message } from 'antd';
import {
  PlusOutlined,
  RobotOutlined,
  MessageOutlined,
  ExperimentOutlined,
  EnvironmentOutlined,
  GlobalOutlined,
} from '@ant-design/icons';
import CopilotV2Drawer from '@/components/CopilotV2Drawer';
import V2ApprovalsInbox from '@/components/V2ApprovalsInbox';
import CesiumMap from '@/components/CesiumMap';

const { Title, Text, Paragraph } = Typography;

interface FocusedDetection {
  id: string;
  drone_id: string | null;
  lat: number;
  lng: number;
  label: string;
  confidence: number;
  at: number;
}

export default function CopilotV2Page() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [focused, setFocused] = useState<FocusedDetection | null>(null);
  const viewerRef = useRef<any>(null);
  // Optional: allow the map to follow a specific drone once focused.
  const [followDrone, setFollowDrone] = useState<string | undefined>(undefined);

  const handleMapReady = useCallback((v: any) => {
    viewerRef.current = v;
  }, []);

  const flyTo = useCallback((lat: number, lng: number) => {
    const v = viewerRef.current;
    if (!v || v.isDestroyed?.()) return false;
    try {
      // CesiumMap exposes Cesium on window once the dynamic import lands.
      const Cesium: any = (window as any).Cesium;
      if (!Cesium) return false;
      v.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(lng, lat, 600),
        duration: 1.2,
        orientation: {
          heading: 0.0,
          pitch: -Cesium.Math.PI_OVER_TWO / 1.5,
          roll: 0.0,
        },
      });
      return true;
    } catch (e) {
      console.warn('[copilot-v2] flyTo failed', e);
      return false;
    }
  }, []);

  const handleDetectionFocus = (d: {
    id: string;
    drone_id: string | null;
    lat?: number | null;
    lng?: number | null;
    label: string;
    confidence: number;
  }) => {
    if (d.lat == null || d.lng == null) {
      message.warning('该检测缺少坐标信息，无法定位');
      return;
    }
    setFocused({
      id: d.id,
      drone_id: d.drone_id,
      lat: d.lat,
      lng: d.lng,
      label: d.label,
      confidence: d.confidence,
      at: Date.now(),
    });
    if (d.drone_id) setFollowDrone(d.drone_id);
    const ok = flyTo(d.lat, d.lng);
    if (ok) {
      message.success(
        `已定位到 ${d.label} @ ${d.lat.toFixed(5)}, ${d.lng.toFixed(5)}`,
      );
    } else {
      message.info(
        `坐标已捕获（地图未就绪）: ${d.lat.toFixed(5)}, ${d.lng.toFixed(5)}`,
      );
    }
  };

  const topHeight = 'calc(60vh - 60px)';
  const mapHeight = 'calc(40vh - 24px)';

  return (
    <div style={{ padding: 16 }}>
      <div style={{ marginBottom: 12 }}>
        <Title level={4} style={{ margin: 0 }}>
          <RobotOutlined /> Copilot v2 · Function Calling · 敏感操作审批
        </Title>
        <Text type="secondary">
          基于 LLM 工具调用循环的智能助理。查询类操作自动执行；敏感操作（下发任务、中止飞行等）会先向指挥员申请批准。
        </Text>
      </div>

      <Row gutter={16} style={{ height: topHeight, marginBottom: 12 }}>
        <Col span={10} style={{ height: '100%' }}>
          <Card
            title={
              <Space>
                <MessageOutlined />
                <span>Copilot v2 会话</span>
              </Space>
            }
            extra={
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => setDrawerOpen(true)}
              >
                打开助理
              </Button>
            }
            style={{ height: '100%' }}
            styles={{
              body: {
                height: 'calc(100% - 56px)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                padding: 24,
              },
            }}
          >
            <div style={{ textAlign: 'center', maxWidth: 400 }}>
              <ExperimentOutlined
                style={{ fontSize: 48, color: '#764ba2', marginBottom: 16 }}
              />
              <Paragraph>
                点击右上角<Text strong>「打开助理」</Text>进入对话界面。
              </Paragraph>
              <Paragraph type="secondary" style={{ fontSize: 12 }}>
                询问 "过去 30 分钟看到了什么?" — 助理会调用 Vision AI，检测行可点击定位到 3D 地球下方。
              </Paragraph>
              <Alert
                type="info"
                showIcon
                style={{ textAlign: 'left', marginTop: 12 }}
                message="可用工具"
                description={
                  <ul style={{ margin: 0, paddingLeft: 20, fontSize: 12 }}>
                    <li>list_drones / get_drone — 查询无人机</li>
                    <li>list_missions — 查询任务</li>
                    <li>list_detections / detection_stats — 视觉 AI</li>
                    <li>get_airspace / get_weather — 查空域和气象</li>
                    <li>
                      <Text type="warning" strong>
                        create_mission / dispatch_mission / abort_mission
                      </Text>
                      {' '}— 需审批
                    </li>
                  </ul>
                }
              />
            </div>
          </Card>
        </Col>

        <Col span={14} style={{ height: '100%' }}>
          <V2ApprovalsInbox />
        </Col>
      </Row>

      <Card
        size="small"
        title={
          <Space>
            <GlobalOutlined />
            <span>3D 战场态势</span>
            {focused && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                · 已定位 <Text code>{focused.label}</Text>
                @ {focused.lat.toFixed(5)}, {focused.lng.toFixed(5)}
              </Text>
            )}
          </Space>
        }
        styles={{ body: { padding: 0 } }}
      >
        <CesiumMap
          droneId={followDrone}
          height={mapHeight}
          onReady={handleMapReady}
          followPrimary={!!followDrone}
        />
      </Card>

      <CopilotV2Drawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        onDetectionFocus={handleDetectionFocus}
      />

      {focused && (
        <Card
          size="small"
          key={focused.at}
          style={{
            position: 'fixed',
            bottom: 16,
            right: 16,
            width: 320,
            zIndex: 1050,
            boxShadow: '0 6px 18px rgba(0,0,0,.15)',
            borderLeft: '3px solid #1677ff',
          }}
          title={
            <Space>
              <EnvironmentOutlined style={{ color: '#1677ff' }} />
              <span style={{ fontSize: 13 }}>已定位到检测</span>
            </Space>
          }
          extra={
            <Button size="small" type="text" onClick={() => setFocused(null)}>
              关闭
            </Button>
          }
        >
          <div style={{ fontSize: 12, lineHeight: 1.8 }}>
            <div>
              <Text strong>标签</Text>:{' '}
              <Text code>{focused.label}</Text>{' '}
              <Text type="secondary">
                ({(focused.confidence * 100).toFixed(1)}%)
              </Text>
            </div>
            <div>
              <Text strong>无人机</Text>:{' '}
              <Text code>
                {focused.drone_id?.slice(0, 8) ?? '未知'}
              </Text>
            </div>
            <div>
              <Text strong>坐标</Text>:{' '}
              <Text code>
                {focused.lat.toFixed(5)}, {focused.lng.toFixed(5)}
              </Text>
            </div>
            <Space size={4} style={{ marginTop: 4 }}>
              <Button
                size="small"
                type="link"
                onClick={() => flyTo(focused.lat, focused.lng)}
              >
                重新飞往
              </Button>
              {focused.drone_id && (
                <Button
                  size="small"
                  type="link"
                  onClick={() => setFollowDrone(focused.drone_id ?? undefined)}
                >
                  跟随无人机
                </Button>
              )}
            </Space>
          </div>
        </Card>
      )}
    </div>
  );
}
