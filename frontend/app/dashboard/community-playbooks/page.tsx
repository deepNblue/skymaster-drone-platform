'use client';

/**
 * T11.3 · Community Playbook 浏览页面。
 *
 * 三栏交互：
 *   顶栏  ->  Tab 切换  approved / 我的（含 pending/rejected）
 *   左侧  ->  Playbook 列表 + 搜索 + tag filter
 *   右侧  ->  详情：DSL 预览 + install / delete / moderate 按钮
 *
 * 未做：
 *   - 无 tag 云 / 排序切换 (先跑起来)
 *   - 无卡片视图 (list 更适合密集元数据)
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import {
  Alert,
  Button,
  Card,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Space,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  ArrowLeftOutlined,
  CheckOutlined,
  CloseOutlined,
  DeleteOutlined,
  DownloadOutlined,
  ReloadOutlined,
  SearchOutlined,
  UploadOutlined,
} from '@ant-design/icons';

import {
  CommunityPlaybook,
  deleteCommunityPlaybook,
  installCommunityPlaybook,
  listCommunityPlaybooks,
  moderateCommunityPlaybook,
  submitCommunityPlaybook,
} from '@/lib/community_playbooks';

const { Title, Text, Paragraph } = Typography;

function currentUserId(): string | null {
  if (typeof window === 'undefined') return null;
  return window.localStorage.getItem('user_id');
}

function currentRole(): string | null {
  if (typeof window === 'undefined') return null;
  return window.localStorage.getItem('user_role');
}

function StatusTag({ status }: { status: string }) {
  const color =
    status === 'approved' ? 'green' :
    status === 'rejected' ? 'red' : 'orange';
  const label =
    status === 'approved' ? '已上架' :
    status === 'rejected' ? '已驳回' : '审核中';
  return <Tag color={color}>{label}</Tag>;
}

export default function CommunityPlaybooksPage() {
  const [tab, setTab] = useState<'public' | 'mine'>('public');
  const [rows, setRows] = useState<CommunityPlaybook[]>([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<CommunityPlaybook | null>(null);
  const [q, setQ] = useState('');
  const [submitOpen, setSubmitOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm();

  const uid = currentUserId();
  const isAdmin = currentRole() === 'admin';

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const data = tab === 'public'
        ? await listCommunityPlaybooks({ status: 'approved' })
        : await listCommunityPlaybooks({ include_own: true });
      setRows(data);
      // Keep selection if slug still present, else drop it.
      if (selected && !data.find((p) => p.slug === selected.slug)) {
        setSelected(null);
      }
    } catch (e: any) {
      message.error(`加载失败: ${e?.message ?? e}`);
    } finally {
      setLoading(false);
    }
  }, [tab, selected]);

  useEffect(() => {
    void reload();
    // reload deliberately depends on `tab` only — selection preservation
    // is handled inside.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  const filtered = useMemo(() => {
    if (!q.trim()) return rows;
    const needle = q.toLowerCase();
    return rows.filter((p) =>
      p.name.toLowerCase().includes(needle) ||
      p.slug.toLowerCase().includes(needle) ||
      p.tags.some((t) => t.toLowerCase().includes(needle)),
    );
  }, [rows, q]);

  const doSubmit = useCallback(async () => {
    let vals: any;
    try {
      vals = await form.validateFields();
    } catch { return; }
    let sample: Record<string, unknown> = {};
    if (vals.sample_inputs?.trim()) {
      try { sample = JSON.parse(vals.sample_inputs); }
      catch (e: any) {
        message.error(`sample_inputs JSON 解析失败: ${e?.message ?? e}`);
        return;
      }
    }
    const tags: string[] = (vals.tags ?? '')
      .split(',').map((t: string) => t.trim()).filter(Boolean);
    setSubmitting(true);
    try {
      await submitCommunityPlaybook({
        slug: vals.slug,
        name: vals.name,
        description: vals.description ?? '',
        dsl_yaml: vals.dsl_yaml,
        sample_inputs: sample,
        tags,
      });
      message.success('已提交, 等待审核');
      setSubmitOpen(false);
      form.resetFields();
      setTab('mine');
    } catch (e: any) {
      message.error(`提交失败: ${e?.message ?? e}`);
    } finally {
      setSubmitting(false);
    }
  }, [form]);

  const doInstall = useCallback(async (slug: string) => {
    try {
      const result = await installCommunityPlaybook(slug);
      message.success(`已安装为 workflow: ${result.workflow_name}`);
      await reload();
    } catch (e: any) {
      message.error(`安装失败: ${e?.message ?? e}`);
    }
  }, [reload]);

  const doDelete = useCallback(async (slug: string) => {
    try {
      await deleteCommunityPlaybook(slug);
      message.success('已删除');
      setSelected(null);
      await reload();
    } catch (e: any) {
      message.error(`删除失败: ${e?.message ?? e}`);
    }
  }, [reload]);

  const doModerate = useCallback(
    async (slug: string, approve: boolean) => {
      let reason: string | undefined;
      if (!approve) {
        reason = window.prompt('驳回原因 (必填, 会展示给作者):') ?? '';
        if (!reason.trim()) {
          message.info('已取消');
          return;
        }
      }
      try {
        await moderateCommunityPlaybook(slug, approve, reason);
        message.success(approve ? '已批准' : '已驳回');
        await reload();
      } catch (e: any) {
        message.error(`审核失败: ${e?.message ?? e}`);
      }
    },
    [reload],
  );

  return (
    <div style={{ padding: 16 }}>
      <div style={{ marginBottom: 12 }}>
        <Space>
          <Link href="/dashboard/copilot-workflows">
            <Button size="small" icon={<ArrowLeftOutlined />}>
              返回编辑器
            </Button>
          </Link>
          <Title level={4} style={{ margin: 0 }}>
            <UploadOutlined /> 社区 Playbook
          </Title>
        </Space>
        <Paragraph type="secondary" style={{ marginTop: 4 }}>
          浏览其他 org 分享的 workflow 模板, 一键安装到自己的 workflows。
          自己也可以上传, 审核通过后其他 org 可安装。
        </Paragraph>
      </div>

      <Space
        style={{ marginBottom: 8, width: '100%', justifyContent: 'space-between' }}
      >
        <Tabs
          activeKey={tab}
          onChange={(k) => setTab(k as 'public' | 'mine')}
          items={[
            { key: 'public', label: '公开库' },
            { key: 'mine', label: '我的提交' },
          ]}
        />
        <Space>
          <Input
            size="small"
            prefix={<SearchOutlined />}
            placeholder="按名称/slug/tag 过滤"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            style={{ width: 240 }}
            allowClear
          />
          <Button
            size="small"
            icon={<ReloadOutlined />}
            onClick={() => void reload()}
          >
            刷新
          </Button>
          <Button
            type="primary"
            size="small"
            icon={<UploadOutlined />}
            onClick={() => setSubmitOpen(true)}
          >
            上传新 Playbook
          </Button>
        </Space>
      </Space>

      <div style={{ display: 'flex', gap: 12 }}>
        {/* Left: list */}
        <Card
          size="small"
          style={{ width: 380 }}
          bodyStyle={{ padding: 4, maxHeight: 600, overflowY: 'auto' }}
        >
          {filtered.length === 0 && !loading ? (
            <Empty
              description={tab === 'mine'
                ? '尚未提交任何 playbook' : '公开库暂无内容'}
              image={Empty.PRESENTED_IMAGE_SIMPLE}
            />
          ) : (
            filtered.map((p) => (
              <div
                key={p.slug}
                onClick={() => setSelected(p)}
                style={{
                  padding: 8,
                  borderRadius: 4,
                  cursor: 'pointer',
                  background: selected?.slug === p.slug
                    ? 'rgba(24, 144, 255, 0.08)' : 'transparent',
                  borderLeft: selected?.slug === p.slug
                    ? '3px solid #1890ff' : '3px solid transparent',
                  marginBottom: 2,
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <Text strong>{p.name}</Text>
                  <StatusTag status={p.status} />
                </div>
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {p.slug} · <DownloadOutlined /> {p.install_count}
                  </Text>
                </div>
                {p.tags.length > 0 && (
                  <div style={{ marginTop: 4 }}>
                    {p.tags.map((t) => (
                      <Tag key={t} style={{ marginRight: 2 }}>{t}</Tag>
                    ))}
                  </div>
                )}
              </div>
            ))
          )}
        </Card>

        {/* Right: detail */}
        <Card size="small" style={{ flex: 1 }}>
          {selected === null ? (
            <Empty description="从左侧选择一个 playbook" />
          ) : (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <div>
                  <Title level={5} style={{ margin: 0 }}>
                    {selected.name} <StatusTag status={selected.status} />
                  </Title>
                  <Text type="secondary">
                    {selected.slug} · <DownloadOutlined /> 安装 {selected.install_count} 次
                  </Text>
                </div>
                <Space>
                  {selected.status === 'approved' && (
                    <Button
                      type="primary"
                      icon={<DownloadOutlined />}
                      onClick={() => void doInstall(selected.slug)}
                    >
                      安装到我的 workflows
                    </Button>
                  )}
                  {isAdmin && selected.status === 'pending' && (
                    <>
                      <Button
                        type="primary"
                        icon={<CheckOutlined />}
                        onClick={() => void doModerate(selected.slug, true)}
                      >
                        批准
                      </Button>
                      <Button
                        danger
                        icon={<CloseOutlined />}
                        onClick={() => void doModerate(selected.slug, false)}
                      >
                        驳回
                      </Button>
                    </>
                  )}
                  {(uid === selected.author_user_id || isAdmin) && (
                    <Popconfirm
                      title="确认删除这个 playbook？"
                      onConfirm={() => void doDelete(selected.slug)}
                    >
                      <Button danger icon={<DeleteOutlined />}>
                        删除
                      </Button>
                    </Popconfirm>
                  )}
                </Space>
              </div>

              {selected.rejected_reason && (
                <Alert
                  type="error"
                  showIcon
                  message="已被驳回"
                  description={selected.rejected_reason}
                  style={{ margin: '8px 0' }}
                />
              )}

              <Paragraph style={{ marginTop: 12 }}>
                {selected.description || (
                  <Text type="secondary">(作者未填写描述)</Text>
                )}
              </Paragraph>

              <Title level={5}>Workflow DSL</Title>
              <pre style={{
                background: '#0f172a',
                color: '#e2e8f0',
                padding: 12,
                borderRadius: 4,
                maxHeight: 320,
                overflow: 'auto',
                fontSize: 12,
              }}>
                {selected.dsl_yaml}
              </pre>

              {Object.keys(selected.sample_inputs).length > 0 && (
                <>
                  <Title level={5} style={{ marginTop: 12 }}>
                    示例 Inputs
                  </Title>
                  <pre style={{
                    background: '#f1f5f9',
                    padding: 8,
                    borderRadius: 4,
                    fontSize: 12,
                  }}>
                    {JSON.stringify(selected.sample_inputs, null, 2)}
                  </pre>
                </>
              )}
            </div>
          )}
        </Card>
      </div>

      {/* Submit modal */}
      <Modal
        title="上传新 Playbook"
        open={submitOpen}
        onCancel={() => setSubmitOpen(false)}
        onOk={() => void doSubmit()}
        confirmLoading={submitting}
        okText="提交审核"
        cancelText="取消"
        width={640}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="slug"
            label="slug (kebab-case, 会自动加 user- 前缀)"
            rules={[
              { required: true },
              { pattern: /^[a-z0-9]+(-[a-z0-9]+)*$/, message: '小写字母/数字/短横线' },
            ]}
          >
            <Input placeholder="landslide-scan" />
          </Form.Item>
          <Form.Item
            name="name"
            label="展示名称"
            rules={[{ required: true, max: 120 }]}
          >
            <Input placeholder="山体滑坡快查" />
          </Form.Item>
          <Form.Item
            name="description"
            label="简介 (最多 500 字)"
          >
            <Input.TextArea rows={2} maxLength={500} showCount />
          </Form.Item>
          <Form.Item
            name="dsl_yaml"
            label="Workflow DSL (YAML)"
            rules={[{ required: true }]}
            help="提交时会用同一条 /validate 校验链, 通不过的话会返回具体错误"
          >
            <Input.TextArea
              rows={8}
              placeholder={'version: "0.1"\nname: my-playbook\nsteps:\n  - id: a\n    tool: list_drones\n    args: {}'}
            />
          </Form.Item>
          <Form.Item
            name="sample_inputs"
            label="示例 Inputs (JSON, 可选)"
          >
            <Input.TextArea rows={2} placeholder="{}" />
          </Form.Item>
          <Form.Item
            name="tags"
            label="Tags (逗号分隔, 最多 8 个)"
          >
            <Input placeholder="emergency, sichuan, landslide" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
