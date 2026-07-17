'use client';

import React, { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import {
  Card, Space, Typography, Button, Upload, Table, Tag, Progress, message,
  Descriptions, Steps, Alert, Statistic, Row, Col,
} from 'antd';
import type { UploadFile } from 'antd';
import {
  InboxOutlined, ThunderboltOutlined, RocketOutlined, ArrowLeftOutlined, CloudUploadOutlined,
  DownloadOutlined, FileZipOutlined,
} from '@ant-design/icons';
import {
  getScene, uploadFile, sceneAction, listArtifacts, artifactDownloadUrl,
  type Scene, type SceneStatus, type Artifact,
} from '@/lib/api';
import { PointCloudViewer } from '@/components/PointCloudViewer';
import { SplatViewer } from '@/components/SplatViewer';
import { publishSceneListing, apiBaseURL } from '@/lib/api';

const { Title, Text, Paragraph } = Typography;
const { Dragger } = Upload;

const STATUS_COLOR: Record<SceneStatus, string> = {
  draft: 'default', ingesting: 'processing', ingested: 'cyan',
  colmap: 'processing', colmap_done: 'cyan',
  training: 'processing', ready: 'green',
  failed: 'red', archived: 'default',
};

const STATUS_LABEL: Record<SceneStatus, string> = {
  draft: '草稿', ingesting: '上传中', ingested: '待处理',
  colmap: 'COLMAP 中', colmap_done: 'COLMAP 完成',
  training: '训练中', ready: '就绪',
  failed: '失败', archived: '已归档',
};

interface UploadProgress {
  filename: string;
  pct: number;
  status: 'uploading' | 'done' | 'error' | 'dedup';
  error?: string;
}

export default function SceneDetailPage() {
  const params = useParams();
  const router = useRouter();
  const sceneId = params.id as string;

  const [scene, setScene] = useState<Scene | null>(null);
  const [loading, setLoading] = useState(false);
  const [uploads, setUploads] = useState<Record<string, UploadProgress>>({});
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [previewBuf, setPreviewBuf] = useState<ArrayBuffer | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewArtifact, setPreviewArtifact] = useState<Artifact | null>(null);
  // T4.12 — live progress snapshot from SSE, distinct from the initial
  // getScene() render. Cleared on unmount.
  const [liveSnapshot, setLiveSnapshot] = useState<{
    status: string;
    n_source_images: number;
    n_points: number | null;
    n_gaussians: number | null;
    psnr_train: number | null;
    error_msg: string | null;
    updated_at: string | null;
    ts: string;
  } | null>(null);
  const [sseConnected, setSseConnected] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const r = await getScene(sceneId);
      setScene(r);
      if (r.status === 'ready' || r.status === 'archived') {
        try {
          const al = await listArtifacts(sceneId);
          setArtifacts(al.artifacts);
        } catch { /* non-fatal */ }
      }
    } catch (e: any) {
      message.error(`加载失败：${e?.response?.data?.detail ?? e?.message ?? e}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [sceneId]);

  // T4.12 — Server-Sent Events for live scene progress.
  //
  // EventSource does NOT support custom headers, so the Bearer token
  // is passed as an ?token= query parameter. The SSE endpoint checks
  // for both header and query token. When the scene reaches a terminal
  // state the server emits an 'event: done' frame, which we use to
  // both close() the EventSource and re-load() to pick up final
  // artifacts.
  useEffect(() => {
    if (!sceneId) return;
    const token = typeof window !== 'undefined'
      ? window.localStorage.getItem('access_token') : null;
    if (!token) return;

    const url = `${apiBaseURL}/api/v1/scenes/${sceneId}/progress.sse?token=${encodeURIComponent(token)}`;
    const es = new EventSource(url, { withCredentials: false });
    es.onopen = () => setSseConnected(true);
    es.onmessage = (ev) => {
      try {
        const snap = JSON.parse(ev.data);
        setLiveSnapshot(snap);
      } catch { /* ignore malformed */ }
    };
    es.addEventListener('done', () => {
      es.close();
      setSseConnected(false);
      // Re-fetch to refresh artifacts + non-live scene fields.
      load();
    });
    es.addEventListener('timeout', () => es.close());
    es.addEventListener('gone', () => es.close());
    es.onerror = () => setSseConnected(false);
    return () => {
      es.close();
      setSseConnected(false);
    };
  }, [sceneId]);

  const handleUpload = async (file: File): Promise<void> => {
    const key = `${file.name}-${file.size}`;
    setUploads(prev => ({
      ...prev,
      [key]: { filename: file.name, pct: 0, status: 'uploading' },
    }));
    try {
      const result = await uploadFile(sceneId, file, 'source_image', pct => {
        setUploads(prev => ({
          ...prev,
          [key]: { ...prev[key], pct: Math.round(pct * 100) },
        }));
      });
      setUploads(prev => ({
        ...prev,
        [key]: {
          ...prev[key],
          pct: 100,
          status: result.dedup ? 'dedup' : 'done',
        },
      }));
      load();  // refresh scene to see the new asset
    } catch (e: any) {
      setUploads(prev => ({
        ...prev,
        [key]: {
          ...prev[key],
          status: 'error',
          error: e?.response?.data?.detail ?? e?.message ?? String(e),
        },
      }));
      message.error(`上传失败 ${file.name}：${e?.response?.data?.detail ?? e?.message}`);
    }
  };

  const doAction = async (
    action: 'ingest' | 'colmap' | 'train' | 'reset' | 'archive',
  ) => {
    try {
      await sceneAction(sceneId, action);
      message.success(`${action} 已执行`);
      load();
    } catch (e: any) {
      message.error(`${action} 失败：${e?.response?.data?.detail ?? e?.message}`);
    }
  };

  const doPreview = async (art: Artifact) => {
    // Hard-cap in-browser preview to 200MB to avoid tab crashes on huge scenes.
    if ((art.size_bytes ?? 0) > 200 * 1024 * 1024) {
      message.warning('文件超过 200MB，请下载到桌面 viewer 查看');
      return;
    }
    setPreviewLoading(true);
    setPreviewArtifact(art);
    try {
      const url = artifactDownloadUrl(sceneId, art.id);
      const resp = await fetch(url, { credentials: 'include' });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const buf = await resp.arrayBuffer();
      setPreviewBuf(buf);
    } catch (e: any) {
      message.error(`预览失败：${e?.message ?? e}`);
      setPreviewArtifact(null);
    } finally {
      setPreviewLoading(false);
    }
  };

  if (!scene) return <div style={{ padding: 24 }}>加载中…</div>;

  const stepIdx = (
    scene.status === 'failed' ? -1 :
    scene.status === 'archived' ? 4 :
    ['draft', 'ingesting'].includes(scene.status) ? 0 :
    ['ingested', 'colmap'].includes(scene.status) ? 1 :
    ['colmap_done', 'training'].includes(scene.status) ? 2 : 3
  );

  const uploadRows = Object.entries(uploads).map(([k, v]) => ({ key: k, ...v }));

  return (
    <div style={{ padding: 24, maxWidth: 1400 }}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => router.push('/dashboard/scenes')}>
            返回列表
          </Button>
          <Title level={3} style={{ margin: 0 }}>
            {scene.name}
            <Tag color={STATUS_COLOR[scene.status]} style={{ marginLeft: 12 }}>
              {STATUS_LABEL[scene.status]}
            </Tag>
          </Title>
        </Space>

        {scene.description && (
          <Paragraph type="secondary">{scene.description}</Paragraph>
        )}

        {/* 流水线进度 */}
        <Card
          title="🔗 流水线进度"
          extra={
            sseConnected ? (
              <Tag color="green" style={{ fontSize: 11 }}>
                🟢 实时同步 (SSE)
              </Tag>
            ) : (
              <Tag color="default" style={{ fontSize: 11 }}>
                ⏸ 静态视图
              </Tag>
            )
          }
        >
          <Steps
            current={stepIdx}
            status={(liveSnapshot?.status ?? scene.status) === 'failed' ? 'error' : undefined}
            items={[
              { title: '草稿', description: '创建场景' },
              { title: '摄入完成', description: `${liveSnapshot?.n_source_images ?? scene.n_source_images} 张源图` },
              { title: 'COLMAP', description: (liveSnapshot?.n_points ?? scene.n_points) ? `${(liveSnapshot?.n_points ?? scene.n_points)!.toLocaleString()} 点` : '待运行' },
              { title: '3DGS', description: (liveSnapshot?.n_gaussians ?? scene.n_gaussians) ? `${(liveSnapshot?.n_gaussians ?? scene.n_gaussians)!.toLocaleString()} 高斯 · ${(liveSnapshot?.psnr_train ?? scene.psnr_train)?.toFixed(1)} dB` : '待训练' },
            ]}
          />
          {(liveSnapshot?.error_msg ?? scene.error_msg) && (
            <Alert
              style={{ marginTop: 16 }}
              type="error" showIcon
              message="流水线错误"
              description={liveSnapshot?.error_msg ?? scene.error_msg}
              action={<Button size="small" onClick={() => doAction('reset')}>重置</Button>}
            />
          )}
          <Space style={{ marginTop: 16 }} wrap>
            {scene.status === 'draft' && scene.n_source_images > 0 && (
              <Button icon={<InboxOutlined />} onClick={() => doAction('ingest')}>
                开始摄入 ({scene.n_source_images} 张)
              </Button>
            )}
            {scene.status === 'ingested' && (
              <Button type="primary" icon={<ThunderboltOutlined />} onClick={() => doAction('colmap')}>
                运行 COLMAP
              </Button>
            )}
            {scene.status === 'colmap_done' && (
              <Button type="primary" icon={<RocketOutlined />} onClick={() => doAction('train')}>
                训练 3DGS
              </Button>
            )}
            {['ready', 'archived'].includes(scene.status) && (
              <Button
                icon={<CloudUploadOutlined />}
                onClick={async () => {
                  const title = window.prompt('发布标题？', scene.name);
                  if (!title) return;
                  try {
                    const listing = await publishSceneListing({
                      scene_id: scene.id,
                      title,
                      license: 'CC-BY-NC',
                      visibility: 'public',
                    });
                    message.success(`已发布：${listing.slug}`);
                  } catch (e: any) {
                    message.error(`发布失败：${e?.response?.data?.detail ?? e?.message}`);
                  }
                }}
              >
                发布到场景商店
              </Button>
            )}
          </Space>
        </Card>

        {/* 指标卡 */}
        <Row gutter={16}>
          <Col span={6}>
            <Card><Statistic title="源图" value={scene.n_source_images} /></Card>
          </Col>
          <Col span={6}>
            <Card><Statistic title="SfM 点数" value={scene.n_points ?? '—'} /></Card>
          </Col>
          <Col span={6}>
            <Card><Statistic title="高斯数" value={scene.n_gaussians ?? '—'} /></Card>
          </Col>
          <Col span={6}>
            <Card><Statistic title="PSNR" value={scene.psnr_train ?? '—'} suffix="dB" precision={1} /></Card>
          </Col>
        </Row>

        {/* 上传 */}
        {['draft', 'ingesting'].includes(scene.status) && (
          <Card title="📤 上传源图 / 视频">
            <Dragger
              multiple
              beforeUpload={file => {
                handleUpload(file as unknown as File);
                return false;  // never let antd auto-upload
              }}
              showUploadList={false}
              accept="image/*,video/mp4,video/quicktime"
            >
              <p className="ant-upload-drag-icon"><InboxOutlined /></p>
              <p className="ant-upload-text">点击或拖拽文件到此区域上传</p>
              <p className="ant-upload-hint">
                支持批量 · 分片 4MiB · 自动 SHA-256 去重 · 网络中断可恢复
              </p>
            </Dragger>
            {uploadRows.length > 0 && (
              <Table
                style={{ marginTop: 16 }}
                size="small"
                dataSource={uploadRows}
                pagination={false}
                columns={[
                  { title: '文件', dataIndex: 'filename' },
                  {
                    title: '进度', dataIndex: 'pct',
                    render: (pct: number, row) => (
                      <Progress
                        percent={pct}
                        size="small"
                        status={row.status === 'error' ? 'exception' : row.status === 'done' || row.status === 'dedup' ? 'success' : 'active'}
                      />
                    ),
                  },
                  {
                    title: '状态', dataIndex: 'status',
                    render: (s: string, row) => {
                      if (s === 'done') return <Tag color="green">已入库</Tag>;
                      if (s === 'dedup') return <Tag color="cyan">去重命中</Tag>;
                      if (s === 'error') return <Tag color="red" title={row.error}>失败</Tag>;
                      return <Tag color="blue">上传中</Tag>;
                    },
                  },
                ]}
              />
            )}
          </Card>
        )}

        {/* Artifacts (trained .ply / .splat downloads) */}
        {artifacts.length > 0 && (
          <Card
            title={<><FileZipOutlined /> 训练产物 · {artifacts.length} 个可下载文件</>}
          >
            <Alert
              type="info" showIcon style={{ marginBottom: 12 }}
              message="用桌面 Gaussian Splatting viewer 打开"
              description={
                <>
                  推荐 <b>SuperSplat</b>（在线，playcanvas.com/supersplat/editor）
                  或 <b>Postshot</b>（本地）· 拖拽 .ply 文件即可查看漫游。
                </>
              }
            />

            {/* T1.4 · 在线点云预览 · T1.5 · splat 预览 */}
            {previewArtifact && (
              <Card
                size="small"
                type="inner"
                style={{ marginBottom: 12 }}
                title={<>🔭 在线预览 · {previewArtifact.filename}</>}
                extra={
                  <Button size="small" onClick={() => {
                    setPreviewArtifact(null);
                    setPreviewBuf(null);
                  }}>关闭</Button>
                }
              >
                {previewArtifact.filename.toLowerCase().endsWith('.splat') ? (
                  <SplatViewer buffer={previewBuf} loading={previewLoading} />
                ) : (
                  <PointCloudViewer buffer={previewBuf} loading={previewLoading} />
                )}
              </Card>
            )}

            <Table
              size="small"
              rowKey="id"
              dataSource={artifacts}
              pagination={false}
              columns={[
                { title: '文件', dataIndex: 'filename', ellipsis: true },
                {
                  title: '类型', dataIndex: 'kind', width: 140,
                  render: (k: string) => <Tag color="purple">{k}</Tag>,
                },
                {
                  title: '大小', dataIndex: 'size_bytes', width: 120,
                  render: (v: number | null) =>
                    v == null ? '—' :
                    v < 1024 * 1024 ? `${(v / 1024).toFixed(1)} KB` :
                    v < 1024 * 1024 * 1024 ? `${(v / 1024 / 1024).toFixed(1)} MB` :
                    `${(v / 1024 / 1024 / 1024).toFixed(2)} GB`,
                },
                {
                  title: '操作', key: 'op', width: 220,
                  render: (_: unknown, row: Artifact) => {
                    const lower = row.filename.toLowerCase();
                    const canPreview =
                      (lower.endsWith('.ply') || lower.endsWith('.splat')) &&
                      (row.size_bytes ?? 0) <= 200 * 1024 * 1024;
                    return (
                      <Space size="small">
                        {canPreview && (
                          <Button
                            size="small"
                            onClick={() => doPreview(row)}
                            loading={previewLoading && previewArtifact?.id === row.id}
                          >
                            预览
                          </Button>
                        )}
                        <Button
                          type="primary" size="small"
                          icon={<DownloadOutlined />}
                          href={artifactDownloadUrl(sceneId, row.id)}
                          target="_blank"
                        >
                          下载
                        </Button>
                      </Space>
                    );
                  },
                },
              ]}
            />
          </Card>
        )}

        {/* Assets 列表 */}
        <Card title={`📁 场景资源（${scene.assets.length}）`}>
          <Table
            size="small"
            rowKey="id"
            dataSource={scene.assets}
            pagination={{ pageSize: 20 }}
            columns={[
              { title: '文件名', dataIndex: 'filename', ellipsis: true },
              {
                title: '类型', dataIndex: 'kind', width: 140,
                render: (k: string) => <Tag>{k}</Tag>,
              },
              {
                title: '大小', dataIndex: 'size_bytes', width: 120,
                render: (v: number | null) =>
                  v == null ? '—' :
                  v < 1024 ? `${v} B` :
                  v < 1024 * 1024 ? `${(v / 1024).toFixed(1)} KB` :
                  v < 1024 * 1024 * 1024 ? `${(v / 1024 / 1024).toFixed(1)} MB` :
                  `${(v / 1024 / 1024 / 1024).toFixed(2)} GB`,
              },
              {
                title: 'SHA-256', dataIndex: 'sha256_hex', width: 200,
                render: (v: string | null) => v ? (
                  <Text code style={{ fontSize: 10 }}>{v.slice(0, 16)}…</Text>
                ) : '—',
              },
            ]}
          />
        </Card>

        <Card size="small" type="inner" title="🔍 元数据">
          <Descriptions column={3} size="small">
            <Descriptions.Item label="ID">
              <Text code>{scene.id}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="坐标系">
              {scene.coord_system || '—'}
            </Descriptions.Item>
            <Descriptions.Item label="Mission">
              {scene.mission_id || '—'}
            </Descriptions.Item>
          </Descriptions>
        </Card>
      </Space>
    </div>
  );
}
