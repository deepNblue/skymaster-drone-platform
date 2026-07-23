'use client';

/**
 * Copilot Tool Policy & Audit Console — v2.1 F4.4.
 *
 * ┌──────────────────────────────────────────────────────────┐
 * │  上: 策略编辑器（allowlist / blocklist / risk cap / gate) │
 * │      + 每个工具的预览决策徽章                              │
 * │  下: 审计流水（近 200 条 + 按状态/工具/风险筛）           │
 * │      + 头部小卡展示 executed / blocked / approval 三档     │
 * └──────────────────────────────────────────────────────────┘
 *
 * Design intentions:
 *   * Preview decisions in-browser so admins see the effect *before*
 *     the PUT round-trip — mirrors backend policy engine exactly.
 *   * All "cap"/"gate" tiers are chip toggles, never free-text.
 *   * Audit table lazily paginates via offset — no infinite scroll to
 *     keep memory sane on large orgs.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert, Button, Card, Col, Empty, Input, Row, Segmented, Select, Space,
  Statistic, Table, Tag, Tooltip, Typography, message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  auditStats, flattenStats, getMyPolicy, listAudits, listTools,
  previewDecision, putMyPolicy, riskColor, riskLabel, statusColor,
  statusLabel, type AuditStatus, type RiskLevel, type ToolAudit,
  type ToolCatalogItem, type ToolPolicy, type ToolPolicyPatch,
} from '@/lib/copilot_tool_policy';

const { Title, Text } = Typography;

const TIERS: RiskLevel[] = ['low', 'medium', 'high', 'critical'];

export default function CopilotToolPolicyPage(): React.ReactElement {
  const [tools, setTools] = useState<ToolCatalogItem[]>([]);
  const [policy, setPolicy] = useState<ToolPolicyPatch>({});
  const [savedPolicy, setSavedPolicy] = useState<ToolPolicy | null>(null);
  const [loadingPolicy, setLoadingPolicy] = useState(true);
  const [saving, setSaving] = useState(false);

  const [audits, setAudits] = useState<ToolAudit[]>([]);
  const [stats, setStats] = useState<Record<string, Record<string, number>>>({});
  const [filterStatus, setFilterStatus] = useState<AuditStatus | ''>('');
  const [filterTool, setFilterTool] = useState<string>('');
  const [filterRisk, setFilterRisk] = useState<RiskLevel | ''>('');
  const [auditLoading, setAuditLoading] = useState(false);

  const reloadTools = useCallback(async () => {
    try { setTools(await listTools()); }
    catch (e) { message.error('加载工具目录失败'); }
  }, []);

  const reloadPolicy = useCallback(async () => {
    setLoadingPolicy(true);
    try {
      const p = await getMyPolicy();
      setSavedPolicy(p);
      setPolicy(p ? {
        allowlist: p.allowlist,
        blocklist: p.blocklist,
        max_risk_level: p.max_risk_level,
        require_approval_above: p.require_approval_above,
      } : {});
    } catch (e) { message.error('加载策略失败'); }
    finally { setLoadingPolicy(false); }
  }, []);

  const reloadAudits = useCallback(async () => {
    setAuditLoading(true);
    try {
      const [a, s] = await Promise.all([
        listAudits({
          tool_name: filterTool || undefined,
          status: (filterStatus || undefined) as AuditStatus | undefined,
          risk_level: (filterRisk || undefined) as RiskLevel | undefined,
          limit: 200,
        }),
        auditStats(),
      ]);
      setAudits(a);
      setStats(s);
    } catch (e) { message.error('加载审计流水失败'); }
    finally { setAuditLoading(false); }
  }, [filterStatus, filterTool, filterRisk]);

  useEffect(() => { reloadTools(); reloadPolicy(); }, [reloadTools, reloadPolicy]);
  useEffect(() => { reloadAudits(); }, [reloadAudits]);

  const savePolicy = async () => {
    setSaving(true);
    try {
      const p = await putMyPolicy(policy);
      setSavedPolicy(p);
      message.success('策略已保存');
      reloadAudits();
    } catch (e) { message.error(String(e)); }
    finally { setSaving(false); }
  };

  // Sort tools by risk desc for quicker scanning
  const sortedTools = useMemo(() => [...tools].sort((a, b) => {
    const order = { critical: 0, high: 1, medium: 2, low: 3 } as const;
    return order[a.risk_level] - order[b.risk_level];
  }), [tools]);

  const leaderboard = useMemo(() => flattenStats(stats), [stats]);
  const totalExec = Object.values(stats.executed ?? {}).reduce((a, b) => a + b, 0);
  const totalBlocked = Object.values(stats.blocked ?? {}).reduce((a, b) => a + b, 0);
  const totalPending = Object.values(stats.approval_required ?? {}).reduce((a, b) => a + b, 0);

  const auditCols: ColumnsType<ToolAudit> = [
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 180,
      render: (v: string | null) => v ? new Date(v).toLocaleString() : '—',
    },
    {
      title: '工具',
      dataIndex: 'tool_name',
      width: 200,
      render: (n: string) => <Text code>{n}</Text>,
    },
    {
      title: '风险',
      dataIndex: 'risk_level',
      width: 90,
      render: (r: RiskLevel) => <Tag color={riskColor(r)}>{riskLabel(r)}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (s: AuditStatus) => <Tag color={statusColor(s)}>{statusLabel(s)}</Tag>,
    },
    {
      title: '延迟',
      dataIndex: 'latency_ms',
      width: 90,
      render: (v: number | null) => v == null ? '—' : `${v}ms`,
    },
    {
      title: '备注',
      dataIndex: 'reason',
      render: (_: unknown, row) => (
        <div>
          {row.reason && <Text type="secondary">{row.reason}</Text>}
          {row.error && <Text type="danger"> · {row.error}</Text>}
        </div>
      ),
    },
  ];

  const toolCols: ColumnsType<ToolCatalogItem> = [
    { title: '工具', dataIndex: 'name', render: (n) => <Text code>{n}</Text> },
    {
      title: '权限', dataIndex: 'permission', width: 90,
      render: (p) => p === 'sensitive'
        ? <Tag color="magenta">sensitive</Tag>
        : <Tag>readonly</Tag>,
    },
    {
      title: '风险', dataIndex: 'risk_level', width: 90,
      render: (r: RiskLevel) => <Tag color={riskColor(r)}>{riskLabel(r)}</Tag>,
    },
    {
      title: '预览决策', width: 220,
      render: (_: unknown, tool: ToolCatalogItem) => {
        const d = previewDecision(tool, policy);
        const color = d.action === 'allowed' ? 'green'
          : d.action === 'blocked' ? 'red' : 'gold';
        return (
          <Tooltip title={d.reason ?? '默认放行'}>
            <Tag color={color}>{
              d.action === 'allowed' ? '放行'
              : d.action === 'blocked' ? '拦截' : '待审批'
            }</Tag>
            {d.reason && <Text type="secondary" style={{ marginLeft: 4 }}>{d.reason}</Text>}
          </Tooltip>
        );
      },
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Title level={3}>Copilot 工具治理</Title>
      <Text type="secondary">
        为组织统一管控 Copilot Agent 的工具调用：白/黑名单、风险上限、审批门槛，所有调用留痕可查。
      </Text>

      {/* 顶部统计 */}
      <Row gutter={12} style={{ marginTop: 16 }}>
        <Col span={8}><Card><Statistic title="累计已执行" value={totalExec} valueStyle={{ color: '#3f8600' }} /></Card></Col>
        <Col span={8}><Card><Statistic title="累计被拦截" value={totalBlocked} valueStyle={{ color: '#cf1322' }} /></Card></Col>
        <Col span={8}><Card><Statistic title="累计待审批" value={totalPending} valueStyle={{ color: '#d48806' }} /></Card></Col>
      </Row>

      {/* 策略编辑 */}
      <Card
        title="策略配置"
        style={{ marginTop: 16 }}
        loading={loadingPolicy}
        extra={
          <Space>
            <Button onClick={reloadPolicy}>撤销</Button>
            <Button type="primary" loading={saving} onClick={savePolicy}>保存策略</Button>
          </Space>
        }
      >
        <Row gutter={16}>
          <Col span={12}>
            <div style={{ marginBottom: 12 }}>
              <Text strong>白名单 <Text type="secondary">（留空 = 允许所有）</Text></Text>
              <Select
                mode="multiple" allowClear style={{ width: '100%' }}
                value={policy.allowlist ?? []}
                onChange={(v) => setPolicy(p => ({ ...p, allowlist: v.length ? v : null }))}
                placeholder="选择放行的工具"
                options={tools.map(t => ({ label: t.name, value: t.name }))}
              />
            </div>
            <div>
              <Text strong>黑名单</Text>
              <Select
                mode="multiple" allowClear style={{ width: '100%' }}
                value={policy.blocklist ?? []}
                onChange={(v) => setPolicy(p => ({ ...p, blocklist: v.length ? v : null }))}
                placeholder="选择永不执行的工具"
                options={tools.map(t => ({ label: t.name, value: t.name }))}
              />
            </div>
          </Col>
          <Col span={12}>
            <div style={{ marginBottom: 12 }}>
              <Text strong>风险上限（超过则拦截）</Text><br />
              <Segmented
                options={[{ label: '不限', value: '' }, ...TIERS.map(t => ({ label: riskLabel(t), value: t }))]}
                value={policy.max_risk_level ?? ''}
                onChange={(v) => setPolicy(p => ({
                  ...p, max_risk_level: (v === '' ? null : v) as RiskLevel | null,
                }))}
              />
            </div>
            <div>
              <Text strong>审批门槛（≥此风险强制审批）</Text><br />
              <Segmented
                options={[{ label: '不限', value: '' }, ...TIERS.map(t => ({ label: riskLabel(t), value: t }))]}
                value={policy.require_approval_above ?? ''}
                onChange={(v) => setPolicy(p => ({
                  ...p, require_approval_above: (v === '' ? null : v) as RiskLevel | null,
                }))}
              />
            </div>
            {savedPolicy?.updated_at && (
              <Alert
                style={{ marginTop: 12 }} type="info" showIcon
                message={`当前生效版本更新于 ${new Date(savedPolicy.updated_at).toLocaleString()}`}
              />
            )}
          </Col>
        </Row>
      </Card>

      {/* 工具目录 + 预览决策 */}
      <Card title="工具目录与决策预览" style={{ marginTop: 16 }}>
        <Table
          rowKey="name" size="small" pagination={false}
          dataSource={sortedTools} columns={toolCols}
        />
      </Card>

      {/* 审计流水 */}
      <Card
        title="审计流水（近 200 条）"
        style={{ marginTop: 16 }}
        extra={<Button onClick={reloadAudits} loading={auditLoading}>刷新</Button>}
      >
        <Space style={{ marginBottom: 12 }} wrap>
          <Select
            allowClear placeholder="按状态筛"
            style={{ width: 140 }}
            value={filterStatus || undefined}
            onChange={(v) => setFilterStatus((v ?? '') as AuditStatus | '')}
            options={[
              { label: '已执行', value: 'executed' },
              { label: '被拦截', value: 'blocked' },
              { label: '待审批', value: 'approval_required' },
              { label: '已拒绝', value: 'rejected' },
              { label: '出错', value: 'error' },
            ]}
          />
          <Select
            allowClear placeholder="按工具筛"
            style={{ width: 220 }}
            value={filterTool || undefined}
            onChange={(v) => setFilterTool(v ?? '')}
            options={tools.map(t => ({ label: t.name, value: t.name }))}
          />
          <Select
            allowClear placeholder="按风险筛"
            style={{ width: 120 }}
            value={filterRisk || undefined}
            onChange={(v) => setFilterRisk((v ?? '') as RiskLevel | '')}
            options={TIERS.map(t => ({ label: riskLabel(t), value: t }))}
          />
        </Space>

        {audits.length === 0
          ? <Empty description="暂无审计记录" />
          : <Table
              rowKey="id" size="small" columns={auditCols}
              dataSource={audits} pagination={{ pageSize: 20 }}
              loading={auditLoading}
              expandable={{
                rowExpandable: (r) => Boolean(r.arguments || r.result_preview),
                expandedRowRender: (r) => (
                  <Space direction="vertical" style={{ width: '100%' }}>
                    {r.arguments && (
                      <div>
                        <Text strong>参数</Text>
                        <Input.TextArea
                          readOnly autoSize
                          value={JSON.stringify(r.arguments, null, 2)}
                        />
                      </div>
                    )}
                    {r.result_preview && (
                      <div>
                        <Text strong>结果预览</Text>
                        <Input.TextArea readOnly autoSize value={r.result_preview} />
                      </div>
                    )}
                  </Space>
                ),
              }}
            />
        }
      </Card>

      {leaderboard.length > 0 && (
        <Card title="工具调用排行" style={{ marginTop: 16 }}>
          <Table
            rowKey="tool" size="small" pagination={false}
            dataSource={leaderboard}
            columns={[
              { title: '工具', dataIndex: 'tool', render: (n) => <Text code>{n}</Text> },
              { title: '已执行', dataIndex: 'executed', width: 100 },
              {
                title: '待审批', dataIndex: 'approval_required', width: 100,
                render: (n: number) => n ? <Tag color="gold">{n}</Tag> : n,
              },
              {
                title: '被拦截', dataIndex: 'blocked', width: 100,
                render: (n: number) => n ? <Tag color="red">{n}</Tag> : n,
              },
            ]}
          />
        </Card>
      )}
    </div>
  );
}
