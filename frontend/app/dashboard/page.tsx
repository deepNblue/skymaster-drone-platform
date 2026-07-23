'use client';

import React from 'react';
import { Row, Col, Card, Statistic, Typography } from 'antd';
import {
  RocketOutlined,
  AimOutlined,
  AuditOutlined,
  AlertOutlined,
  ArrowUpOutlined,
} from '@ant-design/icons';

const { Title } = Typography;

export default function DashboardPage() {
  return (
    <div>
      <Title level={3} style={{ color: 'var(--sm-text-primary)', marginBottom: 24 }}>
        仪表盘
      </Title>
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="在线设备"
              value={12}
              suffix="/ 15"
              prefix={<RocketOutlined />}
              valueStyle={{ color: 'var(--sm-success)' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="今日任务"
              value={7}
              prefix={<AimOutlined />}
              valueStyle={{ color: 'var(--sm-accent)' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="待审批"
              value={3}
              prefix={<AuditOutlined />}
              valueStyle={{ color: '#faad14' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="告警"
              value={1}
              prefix={<AlertOutlined />}
              valueStyle={{ color: 'var(--sm-danger)' }}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={16}>
          <Card title="任务趋势" style={{ minHeight: 320 }}>
            <div
              style={{
                height: 240,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#8b949e',
              }}
            >
              图表占位 · Chart Placeholder
            </div>
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title="设备状态分布" style={{ minHeight: 320 }}>
            <div
              style={{
                height: 240,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#8b949e',
              }}
            >
              图表占位 · Chart Placeholder
            </div>
          </Card>
        </Col>
      </Row>
    </div>
  );
}
