'use client';

/**
 * Copilot 长期记忆管理页 · v2.1 E2.3.
 *
 * 布局:
 *   ┌────────────────────────────────────────────────┐
 *   │ 顶部: 分类统计卡 (preference / fact / ...)      │
 *   │ 中部: 检索栏 (关键词 + kind 多选 + tag 多选)    │
 *   │ 下部: 结果列表 (score, kind 徽章, 内容, 操作)   │
 *   │ 右上: "新增记忆" 按钮 → Modal 表单               │
 *   └────────────────────────────────────────────────┘
 *
 * 设计意图:
 *   * 检索排序完全由后端负责；前端只展示 score 与 reason 做透明化
 *   * 长内容用 snippet 收纳，展开行查看完整内容
 *   * 支持"标记为组织共享"，用不同颜色的徽章标记 scope=org
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert, Button, Card, Col, Empty, Form, Input, InputNumber, Modal,
  Popconfirm, Row, Select, Space, Statistic, Table, Tag, Tooltip,
  Typography, message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  createMemory, daysRemaining, deleteMemory, kindColor, kindLabel,
  memoryStats, searchMemory, snippet,
  type Memory, type MemoryHit, type MemoryKind,
} from '@/lib/copilot_memory';

const { Title, Text } = Typography;

const KINDS: MemoryKind[] = ['preference', 'fact', 'task_history', 'insight'];

export default function CopilotMemoryPage(): React.ReactElement {
  const [hits, setHits] = useState<MemoryHit[]>([]);
  const [stats, setStats] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(false);

  const [q, setQ] = useState('');
  const [kindFilter, setKindFilter] = useState<MemoryKind[]>([]);
  const [tagFilter, setTagFilter] = useState<string[]>([]);

  const [addOpen, setAddOpen] = useState(false);
  const [addForm] = Form.useForm();

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [h, s] = await Promise.all([
        searchMemory({
          q: q || undefined,
          kind: kindFilter.length ? kindFilter : undefined,
          tag: tagFilter.length ? tagFilter : undefined,
          top_k: 50,
        }),
        memoryStats(),
      ]);
      setHits(h);
      setStats(s);
    } catch (e) {
      message.error(String(e));
    } finally {
      setLoading(false);
    }
  }, [q, kindFilter, tagFilter]);

  useEffect(() => { reload(); }, [reload]);

  const submit = async () => {
    try {
      const v = await addForm.validateFields();
      await createMemory({
        kind: v.kind,
        content: v.content,
        scope: v.scope,
        key: v.key || undefined,
        tags: v.tags ? v.tags.split(',').map((x: string) => x.trim()).filter(Boolean) : undefined,
        ttl_days: v.ttl_days ?? undefined,
        weight: v.weight ?? 50,
      });
      message.success('已保存');
      setAddOpen(false);
      addForm.resetFields();
      reload();
    } catch (e) {
      if ((e as any)?.errorFields) return;
      message.error(String(e));
    }
  };

  const remove = async (id: string) => {
    try {
      await deleteMemory(id);
      message.success('已删除');
      reload();
    } catch (e) { message.error(String(e)); }
  };

  // Extract all known tags for the tag-filter Select
  const allTags = useMemo(() => {
    const s = new Set<string>();
    for (const h of hits) (h.memory.tags ?? []).forEach((t) => s.add(t));
    return [...s];
  }, [hits]);

  const cols: ColumnsType<MemoryHit> = [
    {
      title: '类型',
      dataIndex: ['memory', 'kind'],
      width: 90,
      render: (k: MemoryKind) => <Tag color={kindColor(k)}>{kindLabel(k)}</Tag>,
    },
    {
      title: '范围',
      dataIndex: ['memory', 'scope'],
      width: 80,
      render: (s: string) => s === 'org'
        ? <Tag color="volcano">组织</Tag>
        : <Tag>个人</Tag>,
    },
    {
      title: '内容',
      dataIndex: ['memory', 'content'],
      render: (c: string, row) => (
        <Space direction="vertical" size={0} style={{ width: '100%' }}>
          <Text>{snippet(c, 120)}</Text>
          {row.memory.tags && row.memory.tags.length > 0 && (
            <Space size={4} wrap>
              {row.memory.tags.map((t) => <Tag key={t}>{t}</Tag>)}
            </Space>
          )}
        </Space>
      ),
    },
    {
      title: '得分',
      dataIndex: 'score',
      width: 110,
      render: (n: number, row) => (
        <Tooltip title={row.reason}>
          <Text strong>{n.toFixed(1)}</Text>
        </Tooltip>
      ),
    },
    {
      title: '权重/命中',
      width: 110,
      render: (_: unknown, row) => (
        <Space size={4}>
          <Tag>w {row.memory.weight}</Tag>
          <Tag color="cyan">×{row.memory.hit_count}</Tag>
        </Space>
      ),
    },
    {
      title: '有效期',
      width: 100,
      render: (_: unknown, row) => {
        const d = daysRemaining(row.memory);
        if (d == null) return <Text type="secondary">永久</Text>;
        if (d === 0) return <Text type="danger">今日过期</Text>;
        return <Text>{d} 天</Text>;
      },
    },
    {
      title: '操作',
      width: 80,
      render: (_: unknown, row) => (
        <Popconfirm title="删除该记忆？" onConfirm={() => remove(row.memory.id)}>
          <Button danger size="small">删</Button>
        </Popconfirm>
      ),
    },
  ];

  const total = Object.values(stats).reduce((a, b) => a + b, 0);

  return (
    <div style={{ padding: 24 }}>
      <Space style={{ width: '100%', justifyContent: 'space-between' }}>
        <div>
          <Title level={3} style={{ marginBottom: 0 }}>Copilot 长期记忆</Title>
          <Text type="secondary">
            让 Agent 记住你的偏好、组织事实、任务历史；每次对话时自动召回 Top 5 作为上下文。
          </Text>
        </div>
        <Button type="primary" onClick={() => setAddOpen(true)}>新增记忆</Button>
      </Space>

      {/* 统计卡片 */}
      <Row gutter={12} style={{ marginTop: 16 }}>
        {KINDS.map((k) => (
          <Col span={6} key={k}>
            <Card>
              <Statistic
                title={kindLabel(k)} value={stats[k] ?? 0}
                valueStyle={{ color: '#1677ff' }}
              />
            </Card>
          </Col>
        ))}
      </Row>

      {total === 0 && (
        <Alert
          style={{ marginTop: 16 }} type="info" showIcon
          message="尚未沉淀任何长期记忆"
          description={
            <>
              点击右上角 <b>新增记忆</b> 添加一条偏好或事实；
              Agent 后续对话时会自动召回并作为上下文注入。
            </>
          }
        />
      )}

      {/* 检索栏 */}
      <Card style={{ marginTop: 16 }}>
        <Space wrap>
          <Input.Search
            placeholder="关键词检索..."
            allowClear enterButton
            style={{ width: 320 }}
            onSearch={setQ}
          />
          <Select
            mode="multiple" allowClear
            style={{ minWidth: 220 }}
            placeholder="按类型筛"
            value={kindFilter}
            onChange={setKindFilter}
            options={KINDS.map((k) => ({ label: kindLabel(k), value: k }))}
          />
          {allTags.length > 0 && (
            <Select
              mode="multiple" allowClear
              style={{ minWidth: 220 }}
              placeholder="按标签筛"
              value={tagFilter}
              onChange={setTagFilter}
              options={allTags.map((t) => ({ label: t, value: t }))}
            />
          )}
          <Button onClick={reload} loading={loading}>刷新</Button>
        </Space>
      </Card>

      {/* 结果表格 */}
      <Card style={{ marginTop: 16 }}>
        {hits.length === 0
          ? <Empty description="未匹配任何记忆" />
          : <Table
              rowKey={(r) => r.memory.id}
              size="small"
              dataSource={hits}
              columns={cols}
              loading={loading}
              pagination={{ pageSize: 20 }}
              expandable={{
                rowExpandable: (r) => r.memory.content.length > 120
                  || Boolean(r.memory.meta),
                expandedRowRender: (r) => (
                  <Space direction="vertical" style={{ width: '100%' }}>
                    <Input.TextArea
                      readOnly autoSize value={r.memory.content}
                    />
                    {r.memory.meta && (
                      <div>
                        <Text strong>meta</Text>
                        <Input.TextArea
                          readOnly autoSize
                          value={JSON.stringify(r.memory.meta, null, 2)}
                        />
                      </div>
                    )}
                    <Text type="secondary">
                      创建于 {r.memory.created_at
                        ? new Date(r.memory.created_at).toLocaleString()
                        : '—'}
                      {r.memory.last_hit_at && (
                        <> · 最近命中 {new Date(r.memory.last_hit_at).toLocaleString()}</>
                      )}
                    </Text>
                  </Space>
                ),
              }}
            />
        }
      </Card>

      <Modal
        title="新增长期记忆"
        open={addOpen}
        onCancel={() => setAddOpen(false)}
        onOk={submit}
        okText="保存"
        cancelText="取消"
        width={560}
      >
        <Form form={addForm} layout="vertical" initialValues={{
          kind: 'preference', scope: 'user', weight: 60,
        }}>
          <Form.Item
            name="kind" label="类型"
            rules={[{ required: true }]}
          >
            <Select options={KINDS.map((k) => ({ label: kindLabel(k), value: k }))} />
          </Form.Item>
          <Form.Item
            name="content" label="内容"
            rules={[{ required: true, min: 2, max: 4000 }]}
          >
            <Input.TextArea autoSize={{ minRows: 3 }} placeholder="例如: 巡检默认时长 40 分钟" />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="scope" label="共享范围">
                <Select options={[
                  { label: '仅自己', value: 'user' },
                  { label: '组织共享', value: 'org' },
                ]} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="key" label="唯一 key（可选，用于去重覆写）">
                <Input placeholder="default_mission_duration" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="weight" label="权重 (0–100)">
                <InputNumber min={0} max={100} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="ttl_days" label="保留天数 (留空=永久)">
                <InputNumber min={0} max={3650} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="tags" label="标签 (逗号分隔)">
            <Input placeholder="巡检,MRO" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
