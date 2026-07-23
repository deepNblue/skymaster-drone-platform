/**
 * D3.2 · SceneFramesPage — 4DGS timeline slider + frame editor.
 *
 * URL: /dashboard/scenes/[sid]/frames
 *
 * Layout:
 *   Header row: 场景 ID / 总帧数 / 关键帧数 / 平均 PSNR
 *   Timeline card: Slider + 光照条带 + snap-to-keyframe 按钮
 *   Editor card: 当前帧字段编辑 (关键帧/光照/PSNR/备注/时间戳)
 *   Filters row: 只看关键帧 / 按光照过滤
 *   Table: 完整帧列表
 */
'use client';
import {
  Alert, Button, Card, Col, DatePicker, InputNumber, Modal, Row, Select,
  Slider, Space, Statistic, Switch, Table, Tag, Typography, message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import { useParams } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  ChangeReport, LIGHTING_COLOR, LIGHTING_LABEL, LIGHTINGS, Lighting,
  SEVERITY_COLOR_DIFF, SEVERITY_LABEL_DIFF, SceneFrame, Severity,
  TimelineSummary, averagePsnr, deleteFrame, getChangeReport, getFrame,
  getTimelineSummary, lightingRuns, listFrames, nearestKeyframe,
  pointsToMarks, updateFrame,
} from '@/lib/scene_frame';

const { Text } = Typography;


export default function SceneFramesPage() {
  const params = useParams<{ sid: string }>();
  const sid = params?.sid ?? '';

  const [frames, setFrames] = useState<SceneFrame[]>([]);
  const [summary, setSummary] = useState<TimelineSummary | null>(null);
  const [current, setCurrent] = useState<number>(0);
  const [loading, setLoading] = useState(false);
  const [onlyKeyframes, setOnlyKeyframes] = useState(false);
  const [lightingFilter, setLightingFilter] =
    useState<Lighting | null>(null);

  // Editor state.
  const [editFrame, setEditFrame] = useState<SceneFrame | null>(null);
  const [saving, setSaving] = useState(false);

  // D3.4 · change detection
  const [changeReport, setChangeReport] = useState<ChangeReport | null>(null);
  const [changeMinSev, setChangeMinSev] = useState<Severity>('medium');
  const [changeLoading, setChangeLoading] = useState(false);

  const load = useCallback(async () => {
    if (!sid) return;
    setLoading(true);
    try {
      const [f, s] = await Promise.all([
        listFrames(sid, {
          only_keyframes: onlyKeyframes || undefined,
          lighting: lightingFilter ?? undefined,
        }),
        getTimelineSummary(sid),
      ]);
      setFrames(f);
      setSummary(s);
      if (f.length && !f.some((x) => x.frame_index === current)) {
        setCurrent(f[0].frame_index);
      }
    } catch (e: any) {
      message.error(`加载失败: ${e?.message ?? e}`);
    } finally {
      setLoading(false);
    }
  }, [sid, onlyKeyframes, lightingFilter, current]);

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sid, onlyKeyframes, lightingFilter]);

  const currentFrame = useMemo(
    () => frames.find((f) => f.frame_index === current) ?? null,
    [frames, current],
  );

  const runs = useMemo(() => lightingRuns(frames), [frames]);
  const localAvgPsnr = useMemo(() => averagePsnr(frames), [frames]);

  const snapKeyframe = useCallback(() => {
    if (frames.length === 0) return;
    const next = nearestKeyframe(frames, current);
    if (next !== current) {
      setCurrent(next);
      message.info(`已 snap 到关键帧 #${next}`);
    }
  }, [frames, current]);

  const openEditor = useCallback(async () => {
    if (!currentFrame) return;
    try {
      const fresh = await getFrame(sid, current);
      setEditFrame(fresh);
    } catch (e: any) {
      message.error(`加载帧失败: ${e?.message ?? e}`);
    }
  }, [sid, current, currentFrame]);

  const doSave = useCallback(async () => {
    if (!editFrame) return;
    setSaving(true);
    try {
      await updateFrame(sid, editFrame.frame_index, {
        is_keyframe: editFrame.is_keyframe,
        psnr_frame: editFrame.psnr_frame,
        lighting: editFrame.lighting,
        notes: editFrame.notes,
        captured_at: editFrame.captured_at,
      });
      message.success('已保存');
      setEditFrame(null);
      await load();
    } catch (e: any) {
      message.error(`保存失败: ${e?.message ?? e}`);
    } finally {
      setSaving(false);
    }
  }, [editFrame, sid, load]);

  const doDelete = useCallback(async (idx: number) => {
    Modal.confirm({
      title: `确认删除帧 #${idx}?`,
      onOk: async () => {
        try {
          await deleteFrame(sid, idx);
          message.success('已删除');
          await load();
        } catch (e: any) {
          message.error(`删除失败: ${e?.message ?? e}`);
        }
      },
    });
  }, [sid, load]);

  // D3.4 · load change report
  const loadChanges = useCallback(async () => {
    if (!sid) return;
    setChangeLoading(true);
    try {
      const r = await getChangeReport(sid, { min_severity: changeMinSev });
      setChangeReport(r);
    } catch (e: any) {
      message.error(`变化点加载失败: ${e?.message ?? e}`);
    } finally {
      setChangeLoading(false);
    }
  }, [sid, changeMinSev]);

  const minIdx = frames[0]?.frame_index ?? 0;
  const maxIdx = frames[frames.length - 1]?.frame_index ?? 0;

  // Slider marks: highlight keyframes AND change points.
  const marks = useMemo(() => {
    const m: Record<number, {
      style: React.CSSProperties; label: string;
    }> = {};
    frames.filter((f) => f.is_keyframe).forEach((f) => {
      m[f.frame_index] = {
        style: { color: '#fa8c16' },
        label: `⭐${f.frame_index}`,
      };
    });
    // Change points override keyframe marks (usually more urgent).
    if (changeReport) {
      const changeMarks = pointsToMarks(changeReport.change_points);
      for (const [k, v] of Object.entries(changeMarks)) {
        const idx = Number(k);
        m[idx] = {
          style: { color: v.color, fontWeight: 700 },
          label: `${v.label}${
            m[idx] ? '' : ''
          }`,
        };
      }
    }
    return m;
  }, [frames, changeReport]);

  const cols: ColumnsType<SceneFrame> = [
    {
      title: '#',
      dataIndex: 'frame_index',
      key: 'frame_index',
      width: 60,
      render: (v: number, r) => (
        <Space>
          <Text strong>{v}</Text>
          {r.is_keyframe && <Tag color="orange">key</Tag>}
        </Space>
      ),
    },
    {
      title: '时刻',
      dataIndex: 'captured_at',
      key: 'captured_at',
      width: 180,
      render: (v: string | null) =>
        v ? dayjs(v).format('MM-DD HH:mm:ss') : '—',
    },
    {
      title: 'PSNR',
      dataIndex: 'psnr_frame',
      key: 'psnr_frame',
      width: 80,
      render: (v: number | null) =>
        v == null ? '—' : v.toFixed(2),
    },
    {
      title: '光照',
      dataIndex: 'lighting',
      key: 'lighting',
      width: 90,
      render: (v: Lighting | null) => v ? (
        <Tag color={LIGHTING_COLOR[v]}>{LIGHTING_LABEL[v]}</Tag>
      ) : '—',
    },
    {
      title: '备注',
      dataIndex: 'notes',
      key: 'notes',
      ellipsis: true,
      render: (v: string | null) => v ?? '—',
    },
    {
      title: '操作',
      key: 'op',
      width: 140,
      render: (_, r) => (
        <Space>
          <Button size="small" type="link"
            onClick={() => setCurrent(r.frame_index)}
          >定位</Button>
          <Button size="small" type="link" danger
            onClick={() => void doDelete(r.frame_index)}
          >删除</Button>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 16 }}>
      <Typography.Title level={4}>
        4DGS 时间轴 · Scene {sid.slice(0, 8)}
      </Typography.Title>

      {summary && (
        <Card size="small" style={{ marginBottom: 12 }}>
          <Row gutter={16}>
            <Col span={6}>
              <Statistic title="总帧" value={summary.total_frames} />
            </Col>
            <Col span={6}>
              <Statistic title="关键帧"
                value={summary.keyframe_count}
                valueStyle={{ color: '#fa8c16' }}
              />
            </Col>
            <Col span={6}>
              <Statistic title="平均 PSNR"
                value={summary.avg_psnr ?? '—'}
                precision={summary.avg_psnr ? 2 : 0}
                suffix={summary.avg_psnr ? 'dB' : ''}
              />
            </Col>
            <Col span={6}>
              <Statistic title="时长"
                value={
                  summary.captured_at_start && summary.captured_at_end
                    ? `${dayjs(summary.captured_at_end).diff(
                      dayjs(summary.captured_at_start), 'second')}s`
                    : '—'
                }
              />
            </Col>
          </Row>
        </Card>
      )}

      <Card size="small" title="🎞️ 时间轴"
        style={{ marginBottom: 12 }}
        extra={
          <Space>
            <Button onClick={snapKeyframe}>Snap → 最近关键帧</Button>
            <Button type="primary"
              disabled={!currentFrame}
              onClick={() => void openEditor()}
            >编辑当前帧</Button>
          </Space>
        }
      >
        {frames.length === 0 ? (
          <Alert type="info" showIcon
            message="暂无帧数据. 请通过 4DGS 摄取流水线导入."
          />
        ) : (
          <>
            <Slider
              min={minIdx}
              max={maxIdx}
              value={current}
              marks={marks}
              onChange={(v) => setCurrent(Array.isArray(v) ? v[0] : v)}
              step={1}
              tooltip={{ formatter: (v) => `帧 #${v}` }}
            />
            <div style={{ display: 'flex', marginTop: 12, gap: 2 }}>
              {runs.map((r, i) => (
                <div key={i}
                  title={`${r.lighting ?? '未标注'}: ${r.start}-${r.end}`}
                  style={{
                    flex: r.end - r.start + 1,
                    height: 12,
                    background: r.lighting
                      ? `var(--ant-${LIGHTING_COLOR[r.lighting]}-6, #999)`
                      : '#e5e7eb',
                    borderRadius: 2,
                  }}
                />
              ))}
            </div>
            {currentFrame && (
              <div style={{ marginTop: 12 }}>
                <Space size="large" wrap>
                  <Text strong>当前帧 #{currentFrame.frame_index}</Text>
                  {currentFrame.is_keyframe &&
                    <Tag color="orange">⭐ 关键帧</Tag>}
                  {currentFrame.lighting && (
                    <Tag color={LIGHTING_COLOR[currentFrame.lighting]}>
                      {LIGHTING_LABEL[currentFrame.lighting]}
                    </Tag>
                  )}
                  {currentFrame.psnr_frame != null && (
                    <Text>PSNR: {currentFrame.psnr_frame.toFixed(2)} dB</Text>
                  )}
                  {currentFrame.captured_at && (
                    <Text type="secondary">
                      {dayjs(currentFrame.captured_at)
                        .format('YYYY-MM-DD HH:mm:ss')}
                    </Text>
                  )}
                </Space>
                {currentFrame.notes && (
                  <div style={{ marginTop: 4 }}>
                    <Text type="secondary">备注: {currentFrame.notes}</Text>
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </Card>

      <Card size="small" title="🚨 变化检测"
        style={{ marginBottom: 12 }}
        extra={
          <Space>
            <Text type="secondary">最小严重度:</Text>
            <Select value={changeMinSev}
              style={{ width: 100 }}
              onChange={setChangeMinSev}
              options={(['low', 'medium', 'high', 'critical'] as Severity[])
                .map((s) => ({
                  label: SEVERITY_LABEL_DIFF[s], value: s,
                }))
              }
            />
            <Button type="primary" loading={changeLoading}
              onClick={() => void loadChanges()}
            >扫描时间轴</Button>
          </Space>
        }
      >
        {!changeReport ? (
          <Text type="secondary">
            点击"扫描时间轴"检测 PSNR 突降 / 光照突变 / 采集时间间断.
          </Text>
        ) : changeReport.change_points.length === 0 ? (
          <Alert type="success" showIcon
            message={`已扫描 ${changeReport.total_frames} 帧, 未发现问题`}
          />
        ) : (
          <>
            <Space size="middle" style={{ marginBottom: 8 }}>
              <Tag color="red">紧急 {changeReport.critical_count}</Tag>
              <Tag color="volcano">严重 {changeReport.high_count}</Tag>
              <Tag color="orange">中等 {changeReport.medium_count}</Tag>
              <Text type="secondary">
                共 {changeReport.change_points.length} 个变化点
              </Text>
            </Space>
            <div style={{
              maxHeight: 180, overflowY: 'auto',
              border: '1px solid #f0f0f0', borderRadius: 4,
              padding: 8,
            }}>
              {changeReport.change_points.map((p, i) => (
                <div key={i} style={{
                  padding: '4px 0',
                  borderBottom: i < changeReport.change_points.length - 1
                    ? '1px dashed #eee' : 'none',
                }}>
                  <Space size="small">
                    <Tag color={SEVERITY_COLOR_DIFF[p.severity]}
                      style={{ margin: 0 }}
                    >{SEVERITY_LABEL_DIFF[p.severity]}</Tag>
                    <Button type="link" size="small"
                      style={{ padding: 0 }}
                      onClick={() => setCurrent(p.to_index)}
                    >
                      帧 {p.from_index} → {p.to_index}
                    </Button>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {p.reasons.join(' · ')}
                    </Text>
                  </Space>
                </div>
              ))}
            </div>
          </>
        )}
      </Card>

      <Space style={{ marginBottom: 8 }} wrap>
        <Text>过滤:</Text>
        <Switch checked={onlyKeyframes}
          checkedChildren="只看关键帧" unCheckedChildren="全部帧"
          onChange={setOnlyKeyframes}
        />
        <Select allowClear placeholder="按光照过滤"
          style={{ minWidth: 140 }}
          value={lightingFilter ?? undefined}
          onChange={(v) => setLightingFilter(v ?? null)}
          options={LIGHTINGS.map((l) => ({
            label: LIGHTING_LABEL[l], value: l,
          }))}
        />
        {localAvgPsnr != null && (
          <Text type="secondary">
            过滤后平均 PSNR: {localAvgPsnr.toFixed(2)} dB
          </Text>
        )}
      </Space>

      <Table<SceneFrame>
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={frames}
        columns={cols}
        pagination={{ pageSize: 20 }}
      />

      <Modal
        title={editFrame ? `编辑帧 #${editFrame.frame_index}` : ''}
        open={!!editFrame}
        onCancel={() => setEditFrame(null)}
        onOk={() => void doSave()}
        confirmLoading={saving}
        width={480}
      >
        {editFrame && (
          <Space direction="vertical" size="middle"
            style={{ width: '100%' }}>
            <Space>
              <Text>关键帧:</Text>
              <Switch checked={editFrame.is_keyframe}
                onChange={(v) => setEditFrame({
                  ...editFrame, is_keyframe: v,
                })}
              />
            </Space>
            <Space>
              <Text>PSNR:</Text>
              <InputNumber
                value={editFrame.psnr_frame ?? undefined}
                step={0.1}
                onChange={(v) => setEditFrame({
                  ...editFrame,
                  psnr_frame: (v ?? null) as number | null,
                })}
              />
            </Space>
            <Space>
              <Text>光照:</Text>
              <Select allowClear
                style={{ minWidth: 140 }}
                value={editFrame.lighting ?? undefined}
                onChange={(v) => setEditFrame({
                  ...editFrame, lighting: (v ?? null) as Lighting | null,
                })}
                options={LIGHTINGS.map((l) => ({
                  label: LIGHTING_LABEL[l], value: l,
                }))}
              />
            </Space>
            <Space>
              <Text>时间戳:</Text>
              <DatePicker showTime
                value={
                  editFrame.captured_at
                    ? dayjs(editFrame.captured_at) : null
                }
                onChange={(v) => setEditFrame({
                  ...editFrame,
                  captured_at: v ? v.toISOString() : null,
                })}
              />
            </Space>
            <div>
              <Text>备注:</Text>
              <textarea
                style={{
                  width: '100%', minHeight: 60, marginTop: 4,
                  padding: 8, borderRadius: 4,
                  border: '1px solid #d9d9d9',
                }}
                value={editFrame.notes ?? ''}
                onChange={(e) => setEditFrame({
                  ...editFrame, notes: e.target.value || null,
                })}
              />
            </div>
          </Space>
        )}
      </Modal>
    </div>
  );
}
