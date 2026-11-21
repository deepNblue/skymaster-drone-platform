/**
 * Model Marketplace List page — SkyMaster v2.2 E5
 */
import React, { useState, useEffect } from 'react';
import {
  Card,
  Button,
  Space,
  Tag,
  Input,
  Select,
  Pagination,
  Modal,
  Form,
  message,
  Popconfirm,
  Rate,
  Statistic,
} from 'antd';
import {
  PlusOutlined,
  EyeOutlined,
  EditOutlined,
  DeleteOutlined,
  ShoppingCartOutlined,
  StarOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import * as api from './api';
import type { ModelListing, CreateModelRequest } from './types';

const { Search } = Input;
const { Option } = Select;

const CATEGORIES = [
  { label: '目标检测', value: 'detect' },
  { label: '语义分割', value: 'segment' },
  { label: '姿态估计', value: 'pose' },
  { label: '路径规划', value: 'planning' },
  { label: '3D Gaussian Splatting', value: 'gs' },
  { label: '大语言模型', value: 'llm' },
  { label: '视觉语言模型', value: 'vlm' },
  { label: '其他', value: 'other' },
];

export const ModelList: React.FC = () => {
  const navigate = useNavigate();
  const [models, setModels] = useState<ModelListing[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(false);
  const [category, setCategory] = useState<string>();
  const [searchText, setSearchText] = useState<string>();
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [form] = Form.useForm<CreateModelRequest>();

  const fetchModels = async () => {
    setLoading(true);
    try {
      const res = await api.listModels({
        page,
        size: pageSize,
        category,
        search: searchText,
      });
      setModels(res.items);
      setTotal(res.total);
    } catch (e) {
      message.error('加载模型列表失败');
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchModels();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, category]);

  const handleSearch = () => {
    setPage(1);
    fetchModels();
  };

  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      await api.createModel(values);
      message.success('创建成功');
      setCreateModalOpen(false);
      form.resetFields();
      fetchModels();
    } catch (e) {
      message.error('创建失败');
      console.error(e);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await api.deleteModel(id);
      message.success('删除成功');
      fetchModels();
    } catch (e) {
      message.error('删除失败');
      console.error(e);
    }
  };

  const getLicenseLabel = (type: string) => {
    switch (type) {
      case 'free': return '免费';
      case 'one-time': return '一次性购买';
      case 'subscription': return '订阅';
      default: return type;
    }
  };

  const getLicenseColor = (type: string) => {
    switch (type) {
      case 'free': return 'green';
      case 'one-time': return 'blue';
      case 'subscription': return 'orange';
      default: return 'gray';
    }
  };

  const formatPrice = (cents?: number) => {
    if (cents == null || cents === 0) return null;
    return `¥${(cents / 100).toFixed(2)}`;
  };

  return (
    <div style={{ padding: 16, maxWidth: 1024, margin: '0 auto' }}>
      <Space style={{ marginBottom: 16 }} direction="vertical" style={{ width: '100%' }}>
        <Space>
          <h1>模型市场</h1>
        </Space>
        <Space wrap>
          <Select
            placeholder="选择分类"
            allowClear
            style={{ width: 160 }}
            value={category}
            onChange={setCategory}
          >
            {CATEGORIES.map(c => (
              <Option key={c.value} value={c.value}>{c.label}</Option>
            ))}
          </Select>
          <Search
            placeholder="搜索名称/描述"
            allowClear
            style={{ width: 260 }}
            onSearch={handleSearch}
            onChange={e => setSearchText(e.target.value)}
          />
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setCreateModalOpen(true)}
          >
            发布模型
          </Button>
        </Space>
      </Space>

      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        {models.map((model) => (
          <Card
            key={model.id}
            hoverable
            onClick={() => navigate(`/model-marketplace/${model.id}`)}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start' }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8, flexWrap: 'wrap' }}>
                  {!model.published && <Tag color="gray">草稿</Tag>}
                  <Tag color={getLicenseColor(model.licenseType)}>
                    {getLicenseLabel(model.licenseType)}
                  </Tag>
                  {model.tags?.map((t) => <Tag key={t}>{t}</Tag>)}
                </div>
                <h3 style={{ margin: '0 0 8px 0' }}>{model.name}</h3>
                <p
                  style={{
                    margin: 0,
                    color: 'rgba(0,0,0,0.65)',
                    display: '-webkit-box',
                    WebkitLineClamp: 2,
                    WebkitBoxOrient: 'vertical',
                    overflow: 'hidden',
                  }}
                >
                  {model.description}
                </p>
              </div>
              <Space direction="vertical" align="end">
                <Space>
                  {model.averageRating && (
                    <Space>
                      <Rate disabled allowHalf value={model.averageRating} />
                      <span>({model.reviewCount})</span>
                    </Space>
                  )}
                </Space>
                {formatPrice(model.priceCents) && (
                  <Statistic
                    value={formatPrice(model.priceCents)}
                    valueStyle={{ fontSize: 18 }}
                    prefix={''}
                  />
                )}
                <Space>
                  <Button
                    icon={<EyeOutlined />}
                    size="small"
                    onClick={(e) => {
                      e.stopPropagation();
                      navigate(`/model-marketplace/${model.id}`);
                    }}
                  >
                    查看
                  </Button>
                  <Button
                    icon={<EditOutlined />}
                    size="small"
                    onClick={(e) => {
                      e.stopPropagation();
                      // navigate edit page later
                    }}
                  />
                  <Popconfirm
                    title="确定删除此模型吗？"
                    onCancel={(e) => e?.stopPropagation()}
                    onConfirm={(e) => {
                      e?.stopPropagation();
                      handleDelete(model.id);
                    }}
                  >
                    <Button
                      danger
                      size="small"
                      onClick={(e) => e.stopPropagation()}
                    />
                  </Popconfirm>
                </Space>
              </Space>
            </div>

            <div style={{ marginTop: 12, color: 'rgba(0, 0, 0, 0.45)', fontSize: 13 }}>
              <Space size="middle">
                <span><StarOutlined /> {model.purchaseCount} 已购买</span>
                <span>{new Date(model.createdAt).toLocaleDateString()}</span>
              </Space>
            </div>
          </Card>
        ))}
      </Space>

      <div style={{ marginTop: 24, textAlign: 'center' }}>
        <Pagination
          current={page}
          total={total}
          pageSize={pageSize}
          onChange={(p, s) => {
            setPage(p);
            if (s) setPageSize(s);
          }}
          showSizeChanger
        />
      </div>

      <Modal
        title="发布新模型"
        open={createModalOpen}
        onCancel={() => setCreateModalOpen(false)}
        onOk={handleCreate}
        okText="发布"
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label="模型名称"
            rules={[{ required: true, min: 3, max: 128 }]}
          >
            <Input placeholder="无人机电线检测YOLOv8" />
          </Form.Item>
          <Form.Item
            name="description"
            label="模型描述"
            rules={[{ required: true, min: 10 }]}
          >
            <Input.TextArea
              rows={4}
              placeholder="描述模型的用途、性能、适用场景..."
            />
          </Form.Item>
          <Form.Item
            name="category"
            label="分类"
            rules={[{ required: true }]}
          >
            <Select placeholder="选择分类">
              {CATEGORIES.map(c => (
                <Option key={c.value} value={c.value}>{c.label}</Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item
            name="licenseType"
            label="授权方式"
            rules={[{ required: true }]}
            initialValue="free"
          >
            <Select>
              <Option value="free">免费</Option>
              <Option value="one-time">一次性购买</Option>
              <Option value="subscription">订阅</Option>
            </Select>
          </Form.Item>
          <Form.Item
            name="priceCents"
            label="价格（元 × 100）"
            help="免费模型留空"
          >
            <Input type="number" min={0} />
          </Form.Item>
          <Form.Item
            name="tags"
            label="标签"
          >
            <Input placeholder="电线检测, 电力巡检, yolo" />
          </Form.Item>
          <Form.Item
            name="published"
            label="发布状态"
            initialValue={false}
          >
            <Select>
              <Option value={false}>保存为草稿</Option>
              <Option value={true}>立即发布</Option>
            </Select>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};
