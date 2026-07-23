'use client';

import React, { useState } from 'react';
import { Row, Col, Card, Empty, Button, Space, Typography } from 'antd';
import { PlusOutlined, RobotOutlined, MessageOutlined } from '@ant-design/icons';
import CopilotDrawer from '@/components/CopilotDrawer';
import ApprovalsInbox from '@/components/ApprovalsInbox';

const { Title, Text } = Typography;

export default function CopilotPage() {
  const [drawerOpen, setDrawerOpen] = useState(false);

  const contentHeight = 'calc(100vh - 96px)';

  return (
    <div style={{ padding: 16 }}>
      <Row gutter={16} style={{ height: contentHeight }}>
        <Col span={7} style={{ height: '100%' }}>
          <Card
            title={
              <Space>
                <MessageOutlined />
                <span>历史会话</span>
              </Space>
            }
            extra={
              <Button
                type="primary"
                size="small"
                icon={<PlusOutlined />}
                onClick={() => setDrawerOpen(true)}
              >
                新建会话
              </Button>
            }
            style={{ height: '50%' }}
            styles={{
              body: {
                height: 'calc(100% - 56px)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              },
            }}
          >
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="暂无历史会话"
            >
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => setDrawerOpen(true)}
              >
                新建会话
              </Button>
            </Empty>
          </Card>
          <div style={{ height: 12 }} />
          <div style={{ height: 'calc(50% - 12px)' }}>
            <ApprovalsInbox />
          </div>
        </Col>

        <Col span={17} style={{ height: '100%' }}>
          <Card
            title={
              <Space>
                <RobotOutlined />
                <Title level={5} style={{ margin: 0 }}>
                  Copilot 会话中心
                </Title>
              </Space>
            }
            extra={
              <Button
                type="primary"
                icon={<RobotOutlined />}
                onClick={() => setDrawerOpen(true)}
              >
                打开 Copilot
              </Button>
            }
            style={{ height: '100%' }}
            bodyStyle={{
              height: 'calc(100% - 56px)',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              textAlign: 'center',
              padding: 24,
            }}
          >
            <Space direction="vertical" size="large" style={{ maxWidth: 480 }}>
              <RobotOutlined style={{ fontSize: 64, color: '#667eea' }} />
              <Title level={3} style={{ margin: 0 }}>
                您好，我是 SkyMaster Copilot
              </Title>
              <Text type="secondary">
                我可以帮您规划任务、下发指令、查询设备与视频流状态。点击右上角
                「打开 Copilot」开始一次会话。
              </Text>
              <Space wrap>
                <Button onClick={() => setDrawerOpen(true)}>
                  规划一条巡检航线
                </Button>
                <Button onClick={() => setDrawerOpen(true)}>
                  查询当前在线无人机
                </Button>
                <Button onClick={() => setDrawerOpen(true)}>
                  发起紧急返航
                </Button>
              </Space>
            </Space>
          </Card>
        </Col>
      </Row>

      <CopilotDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
    </div>
  );
}
