'use client';

/**
 * E2.5 · Copilot 审批策略管理页.
 *
 * 允许 admin 配置双签规则：
 *   - 强制双签的工具白名单 (dual_sign_tools)
 *   - 风险阈值：达到某等级自动升级双签
 *   - 必需的审批人角色 (required_roles)
 *   - 单签放行角色 (bypass_roles)
 */

import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert, Button, Card, Col, Form, Input, Row, Select, Space, Tag, Typography,
  message,
} from 'antd';
import {
  getPolicy, upsertPolicy, riskColor, type ApprovalPolicy, type RiskLevel,
} from '@/lib/copilot_approval_policy';

const { Title, Text } = Typography;

const RISK_LEVELS: RiskLevel[] = ['low', 'medium', 'high', 'critical'];

export default function CopilotApprovalPolicyPage(): React.ReactElement {
  const [policy, setPolicy] = useState<ApprovalPolicy | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  const reload = useCallback(async () => {
    try {
      const p = await getPolicy();
      setPolicy(p);
      if (p) {
        form.setFieldsValue({
          dual_sign_tools: p.dual_sign_tools?.join(', ') ?? '',
          dual_sign_min_risk: p.dual_sign_min_risk ?? undefined,
          required_roles: p.required_roles?.join(', ') ?? '',
          bypass_roles: p.bypass_roles?.join(', ') ?? '',
        });
      }
    } catch (e) { message.error(String(e)); }
  }, [form]);

  useEffect(() => { reload(); }, [reload]);

  const submit = async () => {
    setSaving(true);
    try {
      const v = await form.validateFields();
      const toList = (s: string) => s ? s.split(',').map((t) => t.trim()).filter(Boolean) : null;
      await upsertPolicy({
        dual_sign_tools: toList(v.dual_sign_tools),
        dual_sign_min_risk: v.dual_sign_min_risk || null,
        required_roles: toList(v.required_roles),
        bypass_roles: toList(v.bypass_roles),
      });
      message.success('策略已保存');
      reload();
    } catch (e) {
      if ((e as any)?.errorFields) return;
      message.error(String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ padding: 24 }}>
      <Title level={3}>Copilot 审批策略</Title>
      <Text type="secondary">
        配置组织级双签/多签规则；Agent 调用敏感工具时依此判定审批要求。
      </Text>

      <Alert
        style={{ marginTop: 16 }} type="info" showIcon
        message="双签策略生效条件（满足任一即升级为双签）"
        description={
          <ul style={{ paddingLeft: 20, margin: 0 }}>
            <li>工具名出现在 <b>dual_sign_tools</b> 白名单</li>
            <li>操作风险等级 ≥ <b>dual_sign_min_risk</b></li>
            <li>若配置了 <b>required_roles</b>，双签必须覆盖所有指定角色</li>
          </ul>
        }
      />

      <Card style={{ marginTop: 16 }} title="当前策略">
        {policy ? (
          <Space direction="vertical" size="small">
            <div>
              强制双签工具：
              {policy.dual_sign_tools?.length
                ? policy.dual_sign_tools.map((t) => <Tag key={t} color="orange">{t}</Tag>)
                : <Text type="secondary">未配置</Text>}
            </div>
            <div>
              风险阈值：
              {policy.dual_sign_min_risk
                ? <Tag color={riskColor(policy.dual_sign_min_risk)}>{policy.dual_sign_min_risk}</Tag>
                : <Text type="secondary">未配置</Text>}
            </div>
            <div>
              必需角色：
              {policy.required_roles?.length
                ? policy.required_roles.map((r) => <Tag key={r}>{r}</Tag>)
                : <Text type="secondary">无</Text>}
            </div>
            <div>
              放行角色：
              {policy.bypass_roles?.length
                ? policy.bypass_roles.map((r) => <Tag key={r} color="green">{r}</Tag>)
                : <Text type="secondary">无</Text>}
            </div>
          </Space>
        ) : (
          <Text type="secondary">尚未配置策略（默认单签）。</Text>
        )}
      </Card>

      <Card style={{ marginTop: 16 }} title="编辑策略">
        <Form form={form} layout="vertical" onFinish={submit}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="dual_sign_tools"
                label="强制双签工具 (逗号分隔)"
                extra="例如: abort_mission, batch_delete_drones"
              >
                <Input placeholder="abort_mission, batch_delete_drones" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="dual_sign_min_risk"
                label="风险阈值"
                extra="操作风险 ≥ 此等级时自动升级为双签"
              >
                <Select
                  allowClear placeholder="不启用"
                  options={RISK_LEVELS.map((r) => ({ label: r, value: r }))}
                />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="required_roles"
                label="必需角色 (逗号分隔)"
                extra="双签必须由这些角色分别签核，例如 admin, compliance"
              >
                <Input placeholder="admin, compliance" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="bypass_roles"
                label="放行角色 (逗号分隔)"
                extra="拥有此角色的用户单签即通过（如 superadmin）"
              >
                <Input placeholder="superadmin" />
              </Form.Item>
            </Col>
          </Row>
          <Space>
            <Button type="primary" htmlType="submit" loading={saving}>保存</Button>
            <Button onClick={reload}>重置</Button>
          </Space>
        </Form>
      </Card>
    </div>
  );
}
