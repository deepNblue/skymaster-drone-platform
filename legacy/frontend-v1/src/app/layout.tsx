'use client';

 import React, { useState } from 'react';
 import { Menu, Layout } from 'antd';
   import {
      DashboardOutlined,
      SafetyCertificateOutlined,
      RobotOutlined,
      CubeOutlined,
      TeamOutlined,
      ShopOutlined,
      ApiOutlined,
      MapOutlined,
      UserOutlined,
      SettingOutlined,
    } from '@ant-design/icons';
import '../src/theme/globals.css';
import type { MenuProps } from 'antd';

const { Header, Sider, Content } = Layout;

type MenuItem = Required<MenuProps>['items'][number];

function getItem(
  label: React.ReactNode,
  key: React.Key,
  icon?: React.ReactNode,
  onClick?: () => void,
): MenuItem {
  return {
    key,
    icon,
    label: <a href={key as string}>{label}</a>,
    onClick,
  } as MenuItem;
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [collapsed, setCollapsed] = useState(false);

    const items: MenuItem[] = [
      getItem('监控仪表盘', '/dashboard', <DashboardOutlined />),
      getItem('飞行报备', '/approval', <SafetyCertificateOutlined />),
      getItem('无人机地图', '/maps', <MapOutlined />),
      getItem('Copilot 任务链', '/copilot', <RobotOutlined />),
      getItem('3DGS 重建', '/scenes', <CubeOutlined />),
      getItem('社区讨论', '/community', <TeamOutlined />),
      getItem('模型市场', '/model-marketplace', <ShopOutlined />),
      getItem('一键微调', '/taas', <ApiOutlined />),
    ];

  return (
    <html lang="zh-CN">
      <body>
        <Layout className="min-h-screen">
          <Sider
            collapsible
            collapsed={collapsed}
            onCollapse={(value) => setCollapsed(value)}
            className="bg-white"
          >
            <div className="h-16 flex items-center justify-center font-bold text-lg">
              {collapsed ? 'SM' : 'SkyMaster'}
            </div>
            <Menu
              mode="inline"
              defaultSelectedKeys={['/dashboard']}
              items={items}
            />
          </Sider>
          <Layout>
            <Content className="m-0 p-0 bg-gray-50 min-h-[calc(100vh-48px)]">
              {children}
            </Content>
          </Layout>
        </Layout>
      </body>
    </html>
  );
}
