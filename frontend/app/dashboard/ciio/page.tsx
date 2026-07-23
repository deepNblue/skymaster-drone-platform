'use client';

import React, { useEffect, useState } from 'react';
import {
  Card, Table, Tag, Space, Typography, Button, Progress, Alert,
  Empty, Descriptions, message,
} from 'antd';
import {
  SafetyOutlined, DownloadOutlined, ReloadOutlined,
  CheckCircleOutlined, WarningOutlined, QuestionCircleOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons';
import { ciioStatus, ciioReportMdUrl, type CiioReport, type CiioStatus } from '@/lib/api';

const { Title, Text, Paragraph } = Typography;

const STATUS_TAG: Record<CiioStatus, { color: string; icon: React.ReactNode; label: string }> = {
  pass: { color: 'green', icon: <CheckCircleOutlined />, label: '通过' },
  partial: { color: 'gold', icon: <WarningOutlined />, label: '部分' },
  fail: { color: 'red', icon: <CloseCircleOutlined />, label: '不通过' },
  unknown: { color: 'default', icon: <QuestionCircleOutlined />, label: '人工核' },
  na: { color: 'default', icon: null, label: '不适用' },
};

const CATEGORY_TITLES: Record<string, string> = {
  A: 'A · 分析识别',
  B: 'B · 安全防护',
  C: 'C · 检测评估',
  D: 'D · 监测预警',
  E: 'E · 事件处置',
  F: 'F · 组织管理',
};

export default function CiioPage() {
  const [report, setReport] = useState<CiioReport | null>(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const r = await ciioStatus();
      setReport(r);
    } catch (e: any) {
      message.error(`加载 CIIO 自评失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleDownload = () => window.open(ciioReportMdUrl(), '_blank');

  const columns = [
    { title: '编号', dataIndex: 'code', width: 100,
      render: (v: string) => <Text code>{v}</Text> },
    { title: '义务', dataIndex: 'title', width: 220,
      render: (t: string, row: any) => (
        <>
          <div style={{ fontWeight: 500 }}>{t}</div>
          <Text type="secondary" style={{ fontSize: 12 }}>{row.obligation_zh}</Text>
        </>
      ),
    },
    { title: '状态', dataIndex: 'status', width: 110,
      render: (s: CiioStatus) => {
        const cfg = STATUS_TAG[s];
        return <Tag color={cfg.color} icon={cfg.icon}>{cfg.label}</Tag>;
      },
    },
    { title: '证据', dataIndex: 'evidence', ellipsis: true,
      render: (v: string) => <Text style={{ fontSize: 12 }}>{v}</Text> },
    { title: '参考', dataIndex: 'references', width: 200,
      render: (refs: string[]) => (
        <Space wrap size={2}>
          {refs.map(r => <Text key={r} code style={{ fontSize: 10 }}>{r}</Text>)}
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24, maxWidth: 1400 }}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>
            <SafetyOutlined /> CIIO 关基自评报告
          </Title>
          <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
            依据《关键信息基础设施安全保护条例》(2021, 745 号) 与 GB/T 39204-2022 生成的自评快照。
            <code>partial</code> 项在生产环境启用相应开关即可转为 <code>pass</code>；
            <code>unknown</code> 项为运营方需人工补充材料的合规项。
          </Paragraph>
        </div>

        {/* 汇总 */}
        <Card
          extra={
            <Space>
              <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
                刷新
              </Button>
              <Button
                type="primary"
                icon={<DownloadOutlined />}
                onClick={handleDownload}
              >
                下载 Markdown
              </Button>
            </Space>
          }
          title="📊 覆盖度总览"
        >
          {report ? (
            <>
              <div style={{ marginBottom: 20 }}>
                <Progress
                  percent={report.coverage_pct}
                  strokeColor={report.coverage_pct >= 80 ? '#52c41a' :
                               report.coverage_pct >= 60 ? '#faad14' : '#ff4d4f'}
                  strokeWidth={16}
                  format={p => `${p}% · ${report.total} 项`}
                />
              </div>
              <Descriptions column={5} size="small" bordered>
                <Descriptions.Item label="✅ 通过">
                  <Tag color="green">{report.counts.pass ?? 0}</Tag>
                </Descriptions.Item>
                <Descriptions.Item label="🟡 部分">
                  <Tag color="gold">{report.counts.partial ?? 0}</Tag>
                </Descriptions.Item>
                <Descriptions.Item label="❌ 不通过">
                  <Tag color="red">{report.counts.fail ?? 0}</Tag>
                </Descriptions.Item>
                <Descriptions.Item label="❓ 人工核">
                  <Tag>{report.counts.unknown ?? 0}</Tag>
                </Descriptions.Item>
                <Descriptions.Item label="生成时间">
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {new Date(report.generated_at).toLocaleString()}
                  </Text>
                </Descriptions.Item>
              </Descriptions>

              {(report.counts.fail ?? 0) > 0 && (
                <Alert
                  style={{ marginTop: 16 }}
                  type="error"
                  showIcon
                  message="存在 fail 项 · 必须整改后再申请等保测评"
                />
              )}
            </>
          ) : (
            <Empty />
          )}
        </Card>

        {/* 分类展示 */}
        {report && Object.entries(CATEGORY_TITLES).map(([cat, title]) => {
          const rows = report.checks.filter(c => c.category === cat);
          if (!rows.length) return null;
          return (
            <Card key={cat} title={title} size="small">
              <Table
                size="small"
                rowKey="code"
                dataSource={rows}
                columns={columns}
                pagination={false}
              />
            </Card>
          );
        })}
      </Space>
    </div>
  );
}
