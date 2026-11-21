'use client';

/**
 * Admin control panel — v1.0 multi-tenant user/org management.
 *
 * Admin-only page. Currently unguarded on the client (the backend
 * enforces admin role); we'll add a role-check middleware once JWT
 * decoding + `useAuthStore.currentRole` is wired up.
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  Layout, Table, Button, Modal, Form, Input, Select, Space, Tag,
  Popconfirm, message, Card, Row, Col, Divider, Typography,
} from 'antd';
import {
  PlusOutlined, UserSwitchOutlined, DeleteOutlined,
  ApartmentOutlined, TeamOutlined, EditOutlined, SearchOutlined,
} from '@ant-design/icons';
import Link from 'next/link';
import RoleGate from '@/components/RoleGate';
import {
  listOrganizations, createOrganization, updateOrganization, deleteOrganization,
  listUsers, createUser, patchUser, deactivateUser,
} from '@/lib/api';

const { Header, Content } = Layout;
const { Title, Text } = Typography;

interface Org { id: string; name: string }
interface User {
  id: string; email: string; role: string;
  org_id: string | null; is_active: boolean;
}

export default function AdminPage() {
  return (
    <RoleGate required="admin">
      <AdminPageInner />
    </RoleGate>
  );
}

function AdminPageInner() {
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [orgFilter, setOrgFilter] = useState<string | undefined>(undefined);
  const [userQuery, setUserQuery] = useState<string>('');
  const [roleFilter, setRoleFilter] = useState<string | undefined>(undefined);
  const [activeFilter, setActiveFilter] = useState<boolean | undefined>(undefined);
  const [orgModal, setOrgModal] = useState(false);
  const [editingOrg, setEditingOrg] = useState<Org | null>(null);
  const [userModal, setUserModal] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [orgForm] = Form.useForm();
  const [userForm] = Form.useForm();

  const loadOrgs = useCallback(async () => {
    try {
      const rows = await listOrganizations();
      setOrgs(rows);
    } catch (e: any) {
      message.error('组织列表加载失败：' + (e?.response?.data?.detail || e.message));
    }
  }, []);

  const loadUsers = useCallback(async () => {
    try {
      const rows = await listUsers({
        org_id: orgFilter,
        q: userQuery || undefined,
        role: roleFilter,
        is_active: activeFilter,
      });
      setUsers(rows);
    } catch (e: any) {
      message.error('用户列表加载失败：' + (e?.response?.data?.detail || e.message));
    }
  }, [orgFilter, userQuery, roleFilter, activeFilter]);

  useEffect(() => { loadOrgs(); }, [loadOrgs]);
  useEffect(() => { loadUsers(); }, [loadUsers]);

  // ------------- Org handlers -------------
  const openOrgModal = (o?: Org) => {
    setEditingOrg(o ?? null);
    orgForm.resetFields();
    if (o) orgForm.setFieldsValue({ name: o.name });
    setOrgModal(true);
  };

  const handleSubmitOrg = async () => {
    try {
      const values = await orgForm.validateFields();
      if (editingOrg) {
        await updateOrganization(editingOrg.id, values.name);
        message.success('组织已更新');
      } else {
        await createOrganization(values.name);
        message.success('组织已创建');
      }
      setOrgModal(false);
      orgForm.resetFields();
      loadOrgs();
    } catch (e: any) {
      if (e?.errorFields) return;
      message.error(e?.response?.data?.detail || '操作失败');
    }
  };

  const handleDeleteOrg = async (org: Org) => {
    try {
      await deleteOrganization(org.id);
      message.success('组织已删除');
      if (orgFilter === org.id) setOrgFilter(undefined);
      loadOrgs();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '删除失败（组织下仍有活跃用户？）');
    }
  };

  // ------------- User handlers -------------
  const openUserModal = (u?: User) => {
    setEditingUser(u ?? null);
    userForm.resetFields();
    if (u) {
      userForm.setFieldsValue({
        email: u.email,
        role: u.role,
        org_id: u.org_id,
        is_active: u.is_active,
      });
    }
    setUserModal(true);
  };

  const handleSubmitUser = async () => {
    try {
      const values = await userForm.validateFields();
      if (editingUser) {
        await patchUser(editingUser.id, {
          role: values.role,
          org_id: values.org_id || undefined,
          is_active: values.is_active,
        });
        message.success('用户已更新');
      } else {
        await createUser({
          email: values.email,
          password: values.password,
          role: values.role,
          org_id: values.org_id || null,
        });
        message.success('用户已创建');
      }
      setUserModal(false);
      loadUsers();
    } catch (e: any) {
      if (e?.errorFields) return;
      message.error(e?.response?.data?.detail || '操作失败');
    }
  };

  const handleDeactivate = async (u: User) => {
    try {
      await deactivateUser(u.id);
      message.success('已停用');
      loadUsers();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '停用失败');
    }
  };

  const orgColumns = [
    {
      title: '组织名', dataIndex: 'name', key: 'name',
      render: (n: string, o: Org) => (
        <Space>
          <span>{n}</span>
        </Space>
      ),
    },
    {
      title: '操作', key: 'action', width: 100,
      render: (_: any, o: Org) => (
        <Space size="small" onClick={(e) => e.stopPropagation()}>
          <Button
            size="small" type="link" icon={<EditOutlined />}
            onClick={() => openOrgModal(o)}
          />
          <Popconfirm
            title={`删除组织 ${o.name} ?`}
            description="仅当组织下无活跃用户时可删除"
            onConfirm={() => handleDeleteOrg(o)}
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Button size="small" type="link" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const userColumns = [
    { title: '邮箱', dataIndex: 'email', key: 'email' },
    {
      title: '角色', dataIndex: 'role', key: 'role',
      render: (r: string) => (
        <Tag color={r === 'admin' ? 'red' : r === 'operator' ? 'blue' : 'default'}>
          {r}
        </Tag>
      ),
    },
    {
      title: '组织', dataIndex: 'org_id', key: 'org_id',
      render: (oid: string | null) => {
        if (!oid) return <Text type="secondary">-</Text>;
        const o = orgs.find((x) => x.id === oid);
        return o ? o.name : <Text code style={{ fontSize: 11 }}>{oid.slice(0, 8)}...</Text>;
      },
    },
    {
      title: '状态', dataIndex: 'is_active', key: 'is_active',
      render: (v: boolean) => (v ? <Tag color="green">在线</Tag> : <Tag>已停用</Tag>),
    },
    {
      title: '操作', key: 'action',
      render: (_: any, u: User) => (
        <Space>
          <Button
            size="small"
            icon={<UserSwitchOutlined />}
            onClick={() => openUserModal(u)}
          >
            编辑
          </Button>
          {u.is_active && (
            <Popconfirm
              title={`确定停用 ${u.email} ?`}
              onConfirm={() => handleDeactivate(u)}
              okText="停用"
              cancelText="取消"
            >
              <Button size="small" icon={<DeleteOutlined />} danger>停用</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <Layout style={{ minHeight: '100vh', background: 'var(--sm-bg-primary)' }}>
      <Header style={{
        background: 'var(--sm-bg-secondary)',
        borderBottom: '1px solid #30363d',
        display: 'flex', alignItems: 'center', gap: 24,
      }}>
        <Title level={4} style={{ color: 'var(--sm-text-primary)', margin: 0 }}>
          SkyMaster · 管理后台
        </Title>
        <Link href="/dashboard/live" style={{ color: 'var(--sm-accent)' }}>
          ← 返回监控
        </Link>
      </Header>

      <Content style={{ padding: 24 }}>
        <Row gutter={16}>
          <Col span={8}>
            <Card
              title={
                <Space>
                  <ApartmentOutlined />
                  <span>组织管理</span>
                  <Tag color="blue">{orgs.length}</Tag>
                </Space>
              }
              extra={
                <Button
                  size="small"
                  icon={<PlusOutlined />}
                  onClick={() => openOrgModal()}
                >
                  新建组织
                </Button>
              }
              style={{ background: 'var(--sm-bg-secondary)' }}
            >
              <Table
                dataSource={orgs}
                columns={orgColumns}
                rowKey="id"
                size="small"
                pagination={false}
                scroll={{ y: 400 }}
                onRow={(row) => ({
                  onClick: () => setOrgFilter(row.id),
                  style: { cursor: 'pointer' },
                })}
              />
              {orgFilter && (
                <>
                  <Divider />
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    过滤中：{orgs.find((o) => o.id === orgFilter)?.name}{' '}
                    <Button size="small" type="link" onClick={() => setOrgFilter(undefined)}>
                      清除
                    </Button>
                  </Text>
                </>
              )}
            </Card>
          </Col>

          <Col span={16}>
            <Card
              title={
                <Space>
                  <TeamOutlined />
                  <span>用户管理</span>
                  <Tag color="blue">{users.length}</Tag>
                </Space>
              }
              extra={
                <Space>
                  <Input
                    size="small"
                    placeholder="搜邮箱..."
                    prefix={<SearchOutlined />}
                    allowClear
                    value={userQuery}
                    onChange={(e) => setUserQuery(e.target.value)}
                    style={{ width: 150 }}
                  />
                  <Select
                    size="small"
                    placeholder="角色"
                    allowClear
                    style={{ width: 100 }}
                    value={roleFilter}
                    onChange={setRoleFilter}
                    options={[
                      { value: 'viewer', label: 'viewer' },
                      { value: 'operator', label: 'operator' },
                      { value: 'admin', label: 'admin' },
                    ]}
                  />
                  <Select
                    size="small"
                    placeholder="状态"
                    allowClear
                    style={{ width: 90 }}
                    value={activeFilter}
                    onChange={setActiveFilter}
                    options={[
                      { value: true, label: '在线' },
                      { value: false, label: '停用' },
                    ]}
                  />
                  <Button
                    type="primary"
                    size="small"
                    icon={<PlusOutlined />}
                    onClick={() => openUserModal()}
                  >
                    新建
                  </Button>
                </Space>
              }
              style={{ background: 'var(--sm-bg-secondary)' }}
            >
              <Table
                dataSource={users}
                columns={userColumns}
                rowKey="id"
                size="small"
                pagination={{ pageSize: 15 }}
              />
            </Card>
          </Col>
        </Row>

        {/* --- Org modal --- */}
        <Modal
          title={editingOrg ? `编辑组织：${editingOrg.name}` : '新建组织'}
          open={orgModal}
          onOk={handleSubmitOrg}
          onCancel={() => setOrgModal(false)}
          okText={editingOrg ? '保存' : '创建'}
          cancelText="取消"
        >
          <Form form={orgForm} layout="vertical">
            <Form.Item
              label="组织名"
              name="name"
              rules={[
                { required: true, message: '请输入组织名' },
                { min: 2, message: '至少 2 个字符' },
              ]}
            >
              <Input placeholder="e.g. 深圳交通执法大队" />
            </Form.Item>
          </Form>
        </Modal>

        {/* --- User modal --- */}
        <Modal
          title={editingUser ? `编辑用户：${editingUser.email}` : '新建用户'}
          open={userModal}
          onOk={handleSubmitUser}
          onCancel={() => setUserModal(false)}
          okText={editingUser ? '保存' : '创建'}
          cancelText="取消"
        >
          <Form form={userForm} layout="vertical">
            {!editingUser && (
              <>
                <Form.Item
                  label="邮箱" name="email"
                  rules={[
                    { required: true, message: '请输入邮箱' },
                    { type: 'email', message: '邮箱格式不正确' },
                  ]}
                >
                  <Input placeholder="operator@org.com" />
                </Form.Item>
                <Form.Item
                  label="初始密码" name="password"
                  rules={[
                    { required: true, message: '请输入密码' },
                    { min: 6, message: '至少 6 个字符' },
                  ]}
                >
                  <Input.Password placeholder="首次登录后建议修改" />
                </Form.Item>
              </>
            )}
            <Form.Item
              label="角色" name="role" initialValue="viewer"
              rules={[{ required: true }]}
            >
              <Select
                options={[
                  { value: 'viewer', label: 'viewer · 只读' },
                  { value: 'operator', label: 'operator · 任务派发' },
                  { value: 'admin', label: 'admin · 全权' },
                ]}
              />
            </Form.Item>
            <Form.Item label="所属组织" name="org_id">
              <Select
                allowClear
                placeholder="(可选)"
                options={orgs.map((o) => ({ value: o.id, label: o.name }))}
              />
            </Form.Item>
            {editingUser && (
              <Form.Item
                label="启用" name="is_active" valuePropName="checked"
              >
                <Select
                  options={[
                    { value: true, label: '在线' },
                    { value: false, label: '停用' },
                  ]}
                />
              </Form.Item>
            )}
          </Form>
        </Modal>
      </Content>
    </Layout>
  );
}
