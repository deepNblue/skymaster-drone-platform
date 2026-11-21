'use client';

import React, { useEffect, useState } from 'react';
import { Layout, Menu, Avatar, Dropdown, Space, Typography, Button } from 'antd';
import {
  DashboardOutlined,
  RocketOutlined,
  AimOutlined,
  ToolOutlined,
  VideoCameraOutlined,
  GlobalOutlined,
  AuditOutlined,
  RobotOutlined,
  SettingOutlined,
  FireOutlined,
  AppstoreOutlined,
  UserOutlined,
  LogoutOutlined,
  SafetyOutlined,
  ThunderboltOutlined,
  DesktopOutlined,
  SafetyCertificateOutlined,
  DatabaseOutlined,
  LockOutlined,
  TeamOutlined,
  EyeOutlined,
  FileTextOutlined,
  ShopOutlined,
  ExperimentOutlined,
  HistoryOutlined,
  CodeOutlined,
} from '@ant-design/icons';
import { useRouter, usePathname } from 'next/navigation';
import { useAuthStore } from '@/lib/store';
import CopilotDrawer from '@/components/CopilotDrawer';

const { Header, Sider, Content } = Layout;
const { Text } = Typography;

// 分组导航（对标司空2：一级 <=9，管理类下沉二级）
const menuItems = [
  { key: '/dashboard', icon: <DashboardOutlined />, label: '仪表盘' },
  { key: '/dashboard/cockpit', icon: <ThunderboltOutlined />, label: '监控大屏' },
  { key: '/dashboard/video-wall', icon: <AppstoreOutlined />, label: '视频九宫格' },
  { key: '/dashboard/live', icon: <GlobalOutlined />, label: '态势' },
  { key: '/dashboard/dji-control', icon: <AimOutlined />, label: 'DJI 摇杆' },
  { key: '/dashboard/calibration', icon: <ToolOutlined />, label: '校准中心' },
  { key: '/dashboard/mission', icon: <RocketOutlined />, label: 'DJI 任务' },
  { key: '/dashboard/preflight', icon: <SafetyCertificateOutlined />, label: '真机联调' },
  { key: '/dashboard/scenarios/12309', icon: <SafetyOutlined />, label: '12309 防控' },
  {
    key: 'grp-flight',
    icon: <RocketOutlined />,
    label: '飞行作业',
    children: [
      { key: '/dashboard/drones', label: '设备' },
      { key: '/dashboard/missions', label: '任务' },
      { key: '/dashboard/streams', label: '视频' },
    ],
  },
  {
    key: 'grp-approval',
    icon: <AuditOutlined />,
    label: '报备审批',
    children: [
      { key: '/dashboard/approvals', label: '飞行审批' },
      { key: '/dashboard/copilot-approvals', label: '审批中心' },
    ],
  },
  {
    key: 'grp-copilot',
    icon: <RobotOutlined />,
    label: 'Copilot',
    children: [
      { key: '/dashboard/copilot', label: 'Copilot' },
      { key: '/dashboard/copilot-v2', label: 'Copilot v2' },
      { key: '/dashboard/copilot-workflows', label: 'Workflow 编辑器' },
      { key: '/dashboard/copilot-task-chain', label: 'Task Chain' },
      { key: '/dashboard/copilot-history', label: 'Workflow 历史' },
      { key: '/dashboard/copilot-traces', label: 'Copilot 追踪' },
      { key: '/dashboard/copilot-tool-policy', label: '工具治理' },
      { key: '/dashboard/copilot-memory', label: '长期记忆' },
      { key: '/dashboard/copilot-approval-policy', label: '审批策略' },
      { key: '/dashboard/copilot-marketplace', label: 'Copilot 市场' },
    ],
  },
  {
    key: 'grp-twin',
    icon: <ThunderboltOutlined />,
    label: '数字孪生',
    children: [
      { key: '/dashboard/scenes', label: '3DGS 场景' },
      { key: '/dashboard/marketplace', label: '场景商店' },
      { key: '/dashboard/model-marketplace', label: '模型商店' },
    ],
  },
  {
    key: 'grp-community',
    icon: <FireOutlined />,
    label: '社区',
    children: [
      { key: '/dashboard/community', label: '社区' },
      { key: '/dashboard/moderation', label: '内容审核' },
    ],
  },
  {
    key: 'grp-security',
    icon: <SafetyCertificateOutlined />,
    label: '安全合规',
    children: [
      { key: '/dashboard/crypto-sm2', label: 'SM2 签名' },
      { key: '/dashboard/audit-export', label: '审计导出' },
      { key: '/dashboard/ciio', label: 'CIIO 自评' },
    ],
  },
  {
    key: 'grp-admin',
    icon: <SettingOutlined />,
    label: '管理',
    children: [
      { key: '/admin', label: '管理后台' },
      { key: '/dashboard/settings', label: '设置' },
    ],
  },
];

// 收集所有叶子路由 key（用于最长前缀匹配高亮）
const leafKeys: string[] = [];
const collectLeafKeys = (items: any[]) => {
  items.forEach((i) => {
    if (i.children) collectLeafKeys(i.children);
    else if (typeof i.key === 'string' && i.key.startsWith('/')) leafKeys.push(i.key);
  });
};
collectLeafKeys(menuItems);

// 当前选中叶子所属分组（用于默认展开）
const groupOf = (leaf: string): string[] => {
  for (const item of menuItems as any[]) {
    if (item.children?.some((c: any) => c.key === leaf)) return [item.key];
  }
  return [];
};

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
    leafKeys
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
          defaultOpenKeys={groupOf(selectedKey)}
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
