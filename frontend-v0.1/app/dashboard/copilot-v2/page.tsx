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
import { Row, Col, Card, Button, Space, Typography, Empty, Alert } from 'antd';
import {
  PlusOutlined,
  RobotOutlined,
  MessageOutlined,
  ExperimentOutlined,
} from '@ant-design/icons';
import CopilotV2Drawer from '@/components/CopilotV2Drawer';
import V2ApprovalsInbox from '@/components/V2ApprovalsInbox';

const { Title, Text, Paragraph } = Typography;

export default function CopilotV2Page() {
  const [drawerOpen, setDrawerOpen] = useState(false);

  const contentHeight = 'calc(100vh - 96px)';

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

      <CopilotV2Drawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
    </div>
  );
}
