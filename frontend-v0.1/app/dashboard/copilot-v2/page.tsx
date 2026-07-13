'use client';

/**
 * Copilot v2 dashboard page — T4.2.
 *
 * 左侧：Copilot 会话（使用 v2 Function Calling loop）
 * 右侧：v2 敏感操作审批工作台
 *
 * 与 v1 的 /dashboard/copilot 页面并存，供逐步迁移。
 */
import React, { useState } from 'react';
import { Row, Col, Card, Button, Space, Typography, Empty, Alert, message } from 'antd';
import {
  PlusOutlined,
  RobotOutlined,
  MessageOutlined,
  ExperimentOutlined,
  EnvironmentOutlined,
} from '@ant-design/icons';
import CopilotV2Drawer from '@/components/CopilotV2Drawer';
import V2ApprovalsInbox from '@/components/V2ApprovalsInbox';

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

  const contentHeight = 'calc(100vh - 96px)';

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
    message.success(
      `已定位到 ${d.label} @ ${d.lat.toFixed(5)}, ${d.lng.toFixed(5)}`,
    );
  };

  return (
    <div style={{ padding: 16 }}>
      <div style={{ marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>
          <RobotOutlined /> Copilot v2 · Function Calling · 敏感操作审批
        </Title>
        <Text type="secondary">
          基于 LLM 工具调用循环的智能助理。查询类操作自动执行；敏感操作（下发任务、中止飞行等）会先向指挥员申请批准。
        </Text>
      </div>

      <Row gutter={16} style={{ height: contentHeight }}>
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
                v2 与 v1 的差别：v2 使用真正的 LLM 工具调用循环，可以自动组合多步工具（查设备 → 查空域 → 规划航线 → 请求批准 → 执行）；v1 使用固定规则解析意图，只做单步操作。
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
            <Text type="secondary" style={{ fontSize: 11 }}>
              （占位：地图/3D 地球集成于 T5.3 完整版接入）
            </Text>
          </div>
        </Card>
      )}
    </div>
  );
}
