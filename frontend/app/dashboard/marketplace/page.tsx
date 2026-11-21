'use client';

/**
 * Scene Marketplace · v2.1 T2.1 · discovery upgrade.
 *
 * Adds: category nav strip, trending shelf, featured banner, sort selector,
 * admin actions (feature/moderate).
 */
import React, { useEffect, useState } from 'react';
import {
  Alert, Badge, Button, Card, Col, Empty, Input, message, Modal, Row,
  Segmented, Select, Space, Spin, Tag,
} from 'antd';
import {
  CloudDownloadOutlined, ReloadOutlined, StarFilled, StarOutlined,
  FireOutlined, StopOutlined, FlagOutlined,
} from '@ant-design/icons';
import {
  browseSceneListingsExtended, cloneSceneListing, fetchCategoryCounts,
  fetchTrendingListings, featureSceneListing, moderateSceneListing,
  fileReport, REPORT_CATEGORIES, REPORT_CATEGORY_LABELS,
  getSceneMarketplaceFacets, type SceneMarketplaceFacets,
  SCENE_CATEGORIES, SCENE_CATEGORY_LABELS,
  type ReportCategory,
  type SceneCategory, type SceneListing, type SceneListingPage,
} from '@/lib/api';

const LICENSE_OPTIONS = ['CC0', 'CC-BY', 'CC-BY-SA', 'CC-BY-NC', 'CC-BY-NC-SA', 'proprietary'];

export default function MarketplacePage() {
  const [page, setPage] = useState<SceneListingPage | null>(null);
  const [trending, setTrending] = useState<SceneListing[]>([]);
  const [categoryCounts, setCategoryCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(false);
  const [q, setQ] = useState('');
  const [licenseFilter, setLicenseFilter] = useState<string | undefined>();
  const [category, setCategory] = useState<SceneCategory | 'all'>('all');
  // T7.12 — richer facets for the filter sidebar (licenses + tags counts)
  const [facets, setFacets] = useState<SceneMarketplaceFacets | null>(null);

  useEffect(() => {
    getSceneMarketplaceFacets().then(setFacets).catch(() => setFacets(null));
  }, []);
  const [sort, setSort] = useState<'recent' | 'popular' | 'featured'>('featured');
  const [minGaussians, setMinGaussians] = useState<number | undefined>();
  const [tagFilter, setTagFilter] = useState<string | undefined>();  // T7.12
  const [offset, setOffset] = useState(0);
  const [isAdmin, setIsAdmin] = useState(false);
  const limit = 12;

  const load = async () => {
    setLoading(true);
    try {
      const [data, cats, trend] = await Promise.all([
        browseSceneListingsExtended({
          q: q || undefined,
          license: licenseFilter,
          min_gaussians: minGaussians,
          category: category === 'all' ? undefined : category,
          tags: tagFilter,   // T7.12 — pipe to backend as CSV
          sort,
          limit,
          offset,
        }),
        fetchCategoryCounts(),
        fetchTrendingListings(6, 7),
      ]);
      setPage(data);
      setCategoryCounts(Object.fromEntries(cats.map(c => [c.category, c.count])));
      setTrending(trend);
    } catch (e: any) {
      message.error(`加载失败：${e?.response?.data?.detail ?? e?.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // Probe admin role via a soft check — try featuring a nil id and see if we
    // get 403 or 404. Simpler: use profile endpoint if it exists.
    (async () => {
      try {
        const { data } = await (await import('@/lib/api')).api.get('/api/v1/auth/me');
        if (data?.role === 'admin' || data?.role === 'superadmin') setIsAdmin(true);
      } catch { /* ignore */ }
    })();
  }, []);
  useEffect(() => { load(); }, [offset, sort, category, tagFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  const doClone = async (listing: SceneListing) => {
    try {
      const res = await cloneSceneListing(listing.id);
      message.success(`已克隆至你的工作区：${res.scene_id.slice(0, 8)}…`);
      load();
    } catch (e: any) {
      message.error(`克隆失败：${e?.response?.data?.detail ?? e?.message}`);
    }
  };

  const doFeature = async (listing: SceneListing) => {
    const featured = !listing.is_featured;
    let note: string | undefined;
    if (featured) {
      const n = window.prompt('推荐语（可选）？');
      note = n || undefined;
    }
    try {
      await featureSceneListing(listing.id, featured, note);
      message.success(featured ? '已加入精选' : '已取消精选');
      load();
    } catch (e: any) {
      message.error(`操作失败：${e?.response?.data?.detail ?? e?.message}`);
    }
  };

  const doModerate = (listing: SceneListing) => {
    Modal.confirm({
      title: `下架 ${listing.title}`,
      content: (
        <div>
          <Input.TextArea
            id="mod-reason"
            rows={3}
            placeholder="下架原因（必填）"
          />
        </div>
      ),
      okText: '下架',
      okButtonProps: { danger: true },
      onOk: async () => {
        const reason = (document.getElementById('mod-reason') as HTMLTextAreaElement)?.value;
        if (!reason) { message.error('需要填写下架原因'); throw new Error(); }
        try {
          await moderateSceneListing(listing.id, 'removed', reason);
          message.success('已下架');
          load();
        } catch (e: any) {
          message.error(`失败：${e?.response?.data?.detail ?? e?.message}`);
        }
      },
    });
  };

  const doReport = (listing: SceneListing) => {
    let selectedCat: ReportCategory = 'copyright';
    Modal.confirm({
      title: `举报 · ${listing.title}`,
      width: 520,
      content: (
        <div>
          <div style={{ marginBottom: 8 }}>举报类型：</div>
          <Select
            defaultValue={selectedCat}
            onChange={(v) => { selectedCat = v as ReportCategory; }}
            style={{ width: '100%', marginBottom: 12 }}
            options={REPORT_CATEGORIES.map(c => ({
              value: c, label: REPORT_CATEGORY_LABELS[c],
            }))}
          />
          <div style={{ marginBottom: 8 }}>详细说明：</div>
          <Input.TextArea id="report-details" rows={4} placeholder="请说明具体问题…" />
          <Alert
            type="warning" showIcon style={{ marginTop: 12 }}
            message="重复举报会被系统折叠。累计 3 名不同用户举报（版权/隐私/敏感/违法）将自动归档待审核。"
          />
        </div>
      ),
      okText: '提交举报',
      onOk: async () => {
        const details = (document.getElementById('report-details') as HTMLTextAreaElement)?.value;
        try {
          const r = await fileReport(listing.id, { category: selectedCat, details });
          if (r.auto_hidden) {
            message.warning('已提交 · 该场景达到自动归档阈值，等待管理员复核');
          } else {
            message.success('举报已提交，管理员会尽快处理');
          }
          load();
        } catch (e: any) {
          message.error(`失败：${e?.response?.data?.detail ?? e?.message}`);
        }
      },
    });
  };

  const formatSize = (n?: number | null) => {
    if (!n) return '—';
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
    return `${n}`;
  };

  const renderCard = (listing: SceneListing, compact = false) => (
    <Card
      key={listing.id}
      hoverable
      size={compact ? 'small' : 'default'}
      title={
        <Space>
          {listing.is_featured && <StarFilled style={{ color: '#faad14' }} />}
          <span style={{ fontWeight: 600 }}>{listing.title}</span>
          {listing.price_cents > 0 && (
            <Tag color="gold">¥ {(listing.price_cents / 100).toFixed(2)}</Tag>
          )}
        </Space>
      }
      extra={
        <Space size={4}>
          {listing.category && (
            <Tag color="blue">
              {SCENE_CATEGORY_LABELS[listing.category as SceneCategory] ?? listing.category}
            </Tag>
          )}
          <Tag color="purple">{listing.license}</Tag>
        </Space>
      }
      actions={[
        <Button
          key="clone" type="link"
          icon={<CloudDownloadOutlined />}
          onClick={() => doClone(listing)}
        >
          克隆
        </Button>,
        <Button
          key="report" type="link" danger
          icon={<FlagOutlined />}
          onClick={() => doReport(listing)}
        >
          举报
        </Button>,
        ...(isAdmin ? [
          <Button
            key="feature" type="link"
            icon={listing.is_featured ? <StarFilled /> : <StarOutlined />}
            onClick={() => doFeature(listing)}
          >
            {listing.is_featured ? '取消精选' : '设为精选'}
          </Button>,
          <Button
            key="mod" type="link" danger
            icon={<StopOutlined />}
            onClick={() => doModerate(listing)}
          >
            下架
          </Button>,
        ] : []),
      ]}
    >
      {listing.is_featured && listing.featured_note && (
        <Alert
          type="warning" showIcon
          message={listing.featured_note}
          style={{ marginBottom: 8 }}
        />
      )}
      <div style={{ opacity: 0.75, minHeight: compact ? 20 : 40, marginBottom: 8 }}>
        {listing.description ?? '（无描述）'}
      </div>
      <Space size={[4, 4]} wrap style={{ marginBottom: 8 }}>
        {(listing.tags ?? []).slice(0, 6).map(t => (
          <Tag key={t}>{t}</Tag>
        ))}
      </Space>
      <div style={{ fontSize: 12, opacity: 0.6 }}>
        高斯 {formatSize(listing.n_gaussians)} ·
        克隆 {listing.clone_count} ·
        浏览 {listing.view_count}
      </div>
    </Card>
  );

  return (
    <div style={{ padding: 24 }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <h1 style={{ margin: 0 }}>🛒 场景商店</h1>
          <div style={{ opacity: 0.6, fontSize: 13 }}>
            跨 org 共享的 3DGS 场景 · 一键克隆到自己的工作区
            {isAdmin && <Tag color="magenta" style={{ marginLeft: 8 }}>管理员</Tag>}
          </div>
        </Col>
        <Col>
          <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
        </Col>
      </Row>

      {/* Category nav */}
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space wrap>
          <Segmented
            value={category}
            onChange={(v) => { setCategory(v as any); setOffset(0); }}
            options={[
              { label: `全部`, value: 'all' },
              ...SCENE_CATEGORIES.map(c => ({
                label: (
                  <span>
                    {SCENE_CATEGORY_LABELS[c]}
                    <Badge
                      count={categoryCounts[c] ?? 0}
                      style={{ backgroundColor: '#8c8c8c', marginLeft: 6 }}
                    />
                  </span>
                ),
                value: c,
              })),
            ]}
          />
        </Space>
      </Card>

      {/* Trending shelf */}
      {trending.length > 0 && (
        <Card
          size="small"
          title={<><FireOutlined /> 近 7 日热门 · Top {trending.length}</>}
          style={{ marginBottom: 12 }}
        >
          <Row gutter={[12, 12]}>
            {trending.map(l => (
              <Col key={l.id} xs={24} sm={12} md={8} lg={6}>
                {renderCard(l, true)}
              </Col>
            ))}
          </Row>
        </Card>
      )}

      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Input.Search
            placeholder="搜索标题/描述"
            allowClear
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onSearch={() => { setOffset(0); load(); }}
            style={{ width: 260 }}
          />
          <Select
            placeholder="License"
            allowClear
            value={licenseFilter}
            onChange={(v) => { setLicenseFilter(v); setOffset(0); load(); }}
            options={
              facets
                ? LICENSE_OPTIONS.map((l) => ({
                    value: l,
                    label: `${l}${facets.licenses[l] ? ` (${facets.licenses[l]})` : ''}`,
                  }))
                : LICENSE_OPTIONS.map((l) => ({ value: l, label: l }))
            }
            style={{ width: 200 }}
          />
          {/* T7.12 — top-tag dropdown driven by /facets. Free-form
              tag input remains an option for power users; this just
              surfaces the most common tags with counts. */}
          {facets && Object.keys(facets.tags).length > 0 && (
            <Select
              placeholder="热门标签"
              allowClear
              showSearch
              value={tagFilter}
              onChange={(v) => { setTagFilter(v || undefined); setOffset(0); load(); }}
              options={Object.entries(facets.tags)
                .slice(0, 20)
                .map(([t, n]) => ({ value: t, label: `${t} (${n})` }))}
              style={{ width: 180 }}
            />
          )}
          <Select
            placeholder="最小高斯数"
            allowClear
            value={minGaussians}
            onChange={(v) => { setMinGaussians(v); setOffset(0); load(); }}
            options={[
              { value: 100_000, label: '≥ 100K' },
              { value: 1_000_000, label: '≥ 1M' },
              { value: 5_000_000, label: '≥ 5M' },
            ]}
            style={{ width: 140 }}
          />
          <Segmented
            value={sort}
            onChange={(v) => { setSort(v as any); setOffset(0); }}
            options={[
              { label: '精选优先', value: 'featured' },
              { label: '最新', value: 'recent' },
              { label: '最热', value: 'popular' },
            ]}
          />
        </Space>
      </Card>

      <Spin spinning={loading}>
        {page && page.items.length === 0 && (
          <Empty description="暂无场景，你也可以在场景详情页点击「发布到商店」" />
        )}
        <Row gutter={[16, 16]}>
          {page?.items.map(listing => (
            <Col key={listing.id} xs={24} sm={12} md={8}>
              {renderCard(listing)}
            </Col>
          ))}
        </Row>
      </Spin>

      {page && page.total > limit && (
        <Row justify="center" style={{ marginTop: 24 }}>
          <Space>
            <Button
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - limit))}
            >上一页</Button>
            <span style={{ opacity: 0.6 }}>
              {offset + 1} – {Math.min(offset + limit, page.total)} / {page.total}
            </span>
            <Button
              disabled={offset + limit >= page.total}
              onClick={() => setOffset(offset + limit)}
            >下一页</Button>
          </Space>
        </Row>
      )}
    </div>
  );
}
