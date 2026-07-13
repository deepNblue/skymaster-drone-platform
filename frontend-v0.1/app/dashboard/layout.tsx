'use client';

import React, { useEffect, useState } from 'react';
import { Layout, Menu, Avatar, Dropdown, Space, Typography, Button } from 'antd';
import {
  DashboardOutlined,
  RocketOutlined,
  AimOutlined,
  VideoCameraOutlined,
  GlobalOutlined,
  AuditOutlined,
  RobotOutlined,
  SettingOutlined,
  UserOutlined,
  LogoutOutlined,
  SafetyOutlined,
  ThunderboltOutlined,
  DesktopOutlined,
  SafetyCertificateOutlined,
  LockOutlined,
  TeamOutlined,
  EyeOutlined,
  FileTextOutlined,
  ShopOutlined,
  ExperimentOutlined,
} from '@ant-design/icons';
import { useRouter, usePathname } from 'next/navigation';
import { useAuthStore } from '@/lib/store';
import CopilotDrawer from '@/components/CopilotDrawer';

const { Header, Sider, Content } = Layout;
const { Text } = Typography;

const menuItems = [
  { key: '/dashboard', icon: <DashboardOutlined />, label: '仪表盘' },
  { key: '/dashboard/drones', icon: <RocketOutlined />, label: '设备' },
  { key: '/dashboard/missions', icon: <AimOutlined />, label: '任务' },
  { key: '/dashboard/streams', icon: <VideoCameraOutlined />, label: '视频' },
  { key: '/dashboard/live', icon: <GlobalOutlined />, label: '实时地图' },
  { key: '/dashboard/approvals', icon: <AuditOutlined />, label: '审批' },
  { key: '/dashboard/copilot', icon: <RobotOutlined />, label: 'Copilot' },
  { key: '/dashboard/copilot-v2', icon: <ExperimentOutlined />, label: 'Copilot v2' },
  { key: '/dashboard/crypto-sm2', icon: <SafetyCertificateOutlined />, label: 'SM2 签名' },
  { key: '/dashboard/audit-export', icon: <FileTextOutlined />, label: '审计导出' },
  { key: '/dashboard/ciio', icon: <SafetyOutlined />, label: 'CIIO 自评' },
  { key: '/dashboard/scenes', icon: <ThunderboltOutlined />, label: '3DGS 场景' },
  { key: '/dashboard/marketplace', icon: <ShopOutlined />, label: '场景商店' },
  { key: '/dashboard/moderation', icon: <SafetyCertificateOutlined />, label: '内容审核' },
  { key: '/admin', icon: <SettingOutlined />, label: '管理后台' },
  { key: '/dashboard/settings', icon: <SettingOutlined />, label: '设置' },
];

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [mounted, setMounted] = useState(false);
  const [copilotOpen, setCopilotOpen] = useState(false);
  const user = useAuthStore((s) => s.user);
  const clear = useAuthStore((s) => s.clear);

  useEffect(() => {
    setMounted(true);
    if (typeof window !== 'undefined' && !localStorage.getItem('access_token')) {
      router.replace('/login');
    }
  }, [router]);

  const handleLogout = async () => {
    // Best-effort server-side revocation (fires POST /auth/logout).
    try {
      const mod = await import('@/lib/api');
      await mod.logout();
    } catch {
      // ignore — clear locally either way
    }
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    clear();
    router.replace('/login');
  };

  const userMenu = {
    items: [
      {
        key: 'profile',
        icon: <UserOutlined />,
        label: '个人资料',
        onClick: () => router.push('/dashboard/profile'),
      },
      {
        key: 'login-history',
        icon: <SafetyOutlined />,
        label: '登录历史',
        onClick: () => router.push('/dashboard/login-history'),
      },
      {
        key: 'sessions',
        icon: <DesktopOutlined />,
        label: '设备与安全',
        onClick: () => router.push('/dashboard/sessions'),
      },
      {
        key: 'approvals',
        icon: <SafetyCertificateOutlined />,
        label: '飞行报备',
        onClick: () => router.push('/dashboard/approvals'),
      },
      {
        key: 'compliance',
        icon: <LockOutlined />,
        label: '国密合规',
        onClick: () => router.push('/dashboard/compliance'),
      },
      {
        key: 'officers',
        icon: <TeamOutlined />,
        label: '三员分立',
        onClick: () => router.push('/dashboard/officers'),
      },
      {
        key: 'vision',
        icon: <EyeOutlined />,
        label: 'Vision AI',
        onClick: () => router.push('/dashboard/vision'),
      },
      {
        key: 'copilot-agent',
        icon: <RobotOutlined />,
        label: 'Copilot',
        onClick: () => router.push('/dashboard/copilot-agent'),
      },
      { type: 'divider' as const },
      { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: handleLogout },
    ],
  };

  if (!mounted) return null;

  const selectedKey =
    menuItems
      .map((i) => i.key)
      .filter((k) => pathname === k || pathname.startsWith(k + '/'))
      .sort((a, b) => b.length - a.length)[0] || '/dashboard';

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        width={220}
        style={{
          background: 'var(--sm-bg-secondary)',
          borderRight: '1px solid #21262d',
        }}
      >
        <div
          style={{
            height: 56,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--sm-accent)',
            fontSize: 18,
            fontWeight: 600,
            letterSpacing: 1,
            borderBottom: '1px solid #21262d',
          }}
        >
          SkyMaster
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
          items={menuItems}
          onClick={({ key }) => router.push(key)}
          style={{ background: 'transparent', borderRight: 0 }}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: 'var(--sm-bg-secondary)',
            padding: '0 24px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: '1px solid #21262d',
            height: 56,
          }}
        >
          <Text style={{ color: 'var(--sm-text-primary)' }}>无人机统一管控平台</Text>
          <Space size={16}>
            <Button
              type="text"
              icon={<RobotOutlined style={{ color: '#a78bfa', fontSize: 18 }} />}
              onClick={() => setCopilotOpen(true)}
              style={{ color: 'var(--sm-text-primary)' }}
            >
              Copilot
            </Button>
            <Dropdown menu={userMenu} placement="bottomRight">
              <Space style={{ cursor: 'pointer', color: 'var(--sm-text-primary)' }}>
                <Avatar icon={<UserOutlined />} />
                <span>{user?.email || 'admin'}</span>
              </Space>
            </Dropdown>
          </Space>
        </Header>
        <Content style={{ padding: 24, background: 'var(--sm-bg-primary)' }}>{children}</Content>
      </Layout>
      <CopilotDrawer open={copilotOpen} onClose={() => setCopilotOpen(false)} />
    </Layout>
  );
}
