'use client';

/**
 * Admin moderation queue — v2.1 T2.2.
 *
 * Two tabs:
 *  - Reports (default) · queue of open user reports · resolve/reject/take-down
 *  - Appeals · authors challenging removals · accept/reject
 */
import React, { useEffect, useState } from 'react';
import {
  Alert, Button, Card, Empty, Input, message, Modal, Space, Table, Tabs, Tag,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  listReports, resolveReport, listAppeals, resolveAppeal,
  REPORT_CATEGORY_LABELS,
  type Report, type Appeal, type ReportCategory,
} from '@/lib/api';

const CATEGORY_COLOR: Record<string, string> = {
  copyright: 'red',
  privacy: 'volcano',
  sensitive_area: 'magenta',
  illegal: 'red',
  spam: 'default',
  other: 'default',
};

const STATUS_COLOR: Record<string, string> = {
  open: 'gold',
  reviewing: 'processing',
  accepted: 'success',
  rejected: 'default',
  duplicate: 'default',
  pending: 'gold',
  withdrawn: 'default',
};

export default function ModerationPage() {
  const [tab, setTab] = useState<'reports' | 'appeals'>('reports');
  const [reports, setReports] = useState<Report[]>([]);
  const [reportsTotal, setReportsTotal] = useState(0);
  const [appeals, setAppeals] = useState<Appeal[]>([]);
  const [appealsTotal, setAppealsTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>('open');

  const load = async () => {
    setLoading(true);
    try {
      if (tab === 'reports') {
        const r = await listReports({ status: statusFilter === 'all' ? undefined : statusFilter, limit: 100 });
        setReports(r.items);
        setReportsTotal(r.total);
      } else {
        const a = await listAppeals({
          status: statusFilter === 'all' ? undefined : statusFilter === 'open' ? 'pending' : statusFilter,
          limit: 100,
        });
        setAppeals(a.items);
        setAppealsTotal(a.total);
      }
    } catch (e: any) {
      message.error(`加载失败：${e?.response?.data?.detail ?? e?.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [tab, statusFilter]); // eslint-disable-line

  const doResolveReport = (report: Report, action: 'accept' | 'reject' | 'duplicate') => {
    Modal.confirm({
      title: {
        accept: `确认举报成立并下架 · ${report.category}`,
        reject: '驳回该举报',
        duplicate: '标记为重复举报',
      }[action],
      content: (
        <div>
          <div style={{ marginBottom: 8, opacity: 0.7 }}>举报详情：{report.details ?? '无'}</div>
          {action === 'accept' && (
            <Input.TextArea id="mod-reason" rows={3} placeholder="下架原因（必填，写入审计日志）" />
          )}
          <Input.TextArea id="mod-note" rows={2} placeholder="内部备注（可选）" style={{ marginTop: 8 }} />
        </div>
      ),
      okText: action === 'accept' ? '下架' : '确认',
      okButtonProps: { danger: action === 'accept' },
      onOk: async () => {
        const reason = (document.getElementById('mod-reason') as HTMLTextAreaElement)?.value;
        const note = (document.getElementById('mod-note') as HTMLTextAreaElement)?.value;
        try {
          const status = action === 'accept' ? 'accepted' : action === 'reject' ? 'rejected' : 'duplicate';
          await resolveReport(report.id, {
            new_status: status,
            take_down_reason: action === 'accept' ? reason : undefined,
            note: note || undefined,
          });
          message.success('已处理');
          load();
        } catch (e: any) {
          message.error(`失败：${e?.response?.data?.detail ?? e?.message}`);
        }
      },
    });
  };

  const doResolveAppeal = (appeal: Appeal, accept: boolean) => {
    Modal.confirm({
      title: accept ? '接受申诉并恢复上架' : '驳回申诉',
      content: (
        <div>
          <div style={{ marginBottom: 8, opacity: 0.7 }}>申诉理由：{appeal.appeal_message}</div>
          <Input.TextArea id="appeal-note" rows={3} placeholder="审核备注" />
        </div>
      ),
      okText: accept ? '接受' : '驳回',
      okButtonProps: { danger: !accept },
      onOk: async () => {
        const note = (document.getElementById('appeal-note') as HTMLTextAreaElement)?.value;
        try {
          await resolveAppeal(appeal.id, accept, note || undefined);
          message.success('已处理');
          load();
        } catch (e: any) {
          message.error(`失败：${e?.response?.data?.detail ?? e?.message}`);
        }
      },
    });
  };

  const reportCols: ColumnsType<Report> = [
    {
      title: '类型', dataIndex: 'category', width: 130,
      render: (c: string) => (
        <Tag color={CATEGORY_COLOR[c]}>{REPORT_CATEGORY_LABELS[c as ReportCategory] ?? c}</Tag>
      ),
    },
    { title: '举报 listing', dataIndex: 'listing_id', ellipsis: true },
    { title: '详情', dataIndex: 'details', ellipsis: true },
    {
      title: '状态', dataIndex: 'status', width: 100,
      render: (s: string) => <Tag color={STATUS_COLOR[s]}>{s}</Tag>,
    },
    {
      title: '操作', width: 240, key: 'action',
      render: (_, report) => report.status === 'open' || report.status === 'reviewing' ? (
        <Space size="small">
          <Button size="small" danger onClick={() => doResolveReport(report, 'accept')}>
            下架
          </Button>
          <Button size="small" onClick={() => doResolveReport(report, 'reject')}>
            驳回
          </Button>
          <Button size="small" type="link" onClick={() => doResolveReport(report, 'duplicate')}>
            标记重复
          </Button>
        </Space>
      ) : (
        <span style={{ opacity: 0.5 }}>已处理</span>
      ),
    },
  ];

  const appealCols: ColumnsType<Appeal> = [
    { title: '#', dataIndex: 'appeal_seq', width: 50 },
    { title: 'listing', dataIndex: 'listing_id', ellipsis: true },
    { title: '申诉理由', dataIndex: 'appeal_message', ellipsis: true },
    {
      title: '状态', dataIndex: 'status', width: 100,
      render: (s: string) => <Tag color={STATUS_COLOR[s]}>{s}</Tag>,
    },
    {
      title: '操作', width: 200, key: 'action',
      render: (_, appeal) => appeal.status === 'pending' ? (
        <Space size="small">
          <Button size="small" type="primary" onClick={() => doResolveAppeal(appeal, true)}>
            接受恢复
          </Button>
          <Button size="small" danger onClick={() => doResolveAppeal(appeal, false)}>
            驳回
          </Button>
        </Space>
      ) : (
        <span style={{ opacity: 0.5 }}>已处理</span>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <h1 style={{ margin: 0 }}>🛡️ 内容审核工作台</h1>
      <div style={{ opacity: 0.6, fontSize: 13, marginBottom: 16 }}>
        用户举报聚合视图 + 作者申诉复核 · 仅管理员可见
      </div>

      <Alert
        type="info"
        showIcon
        message="自动下架机制"
        description={`同一场景收到 ≥3 名不同用户举报（版权/隐私/敏感区域/违法），系统会自动将 listing 归档待审核，避免高危内容长时间在线。管理员在此确认最终处置。`}
        style={{ marginBottom: 16 }}
      />

      <Card size="small" style={{ marginBottom: 16 }}>
        <Space>
          <span>状态过滤：</span>
          {['open', 'accepted', 'rejected', 'all'].map(s => (
            <Button
              key={s} size="small"
              type={statusFilter === s ? 'primary' : 'default'}
              onClick={() => setStatusFilter(s)}
            >
              {s === 'open' ? (tab === 'reports' ? '待处理' : '待复核') : s}
            </Button>
          ))}
        </Space>
      </Card>

      <Tabs
        activeKey={tab}
        onChange={(k) => setTab(k as any)}
        items={[
          {
            key: 'reports',
            label: `举报队列 (${reportsTotal})`,
            children: (
              <Table
                rowKey="id"
                loading={loading}
                columns={reportCols}
                dataSource={reports}
                pagination={{ pageSize: 20 }}
                locale={{ emptyText: <Empty description="暂无举报" /> }}
              />
            ),
          },
          {
            key: 'appeals',
            label: `申诉队列 (${appealsTotal})`,
            children: (
              <Table
                rowKey="id"
                loading={loading}
                columns={appealCols}
                dataSource={appeals}
                pagination={{ pageSize: 20 }}
                locale={{ emptyText: <Empty description="暂无申诉" /> }}
              />
            ),
          },
        ]}
      />
    </div>
  );
}
