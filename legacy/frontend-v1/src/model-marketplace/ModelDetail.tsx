/**
 * Model Detail page with reviews — SkyMaster v2.2 E5
 */
import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Card,
  Button,
  Space,
  Tag,
  Rate,
  List,
  Comment,
  Form,
  Input,
  message,
  Avatar,
  Alert,
  Divider,
  Statistic,
} from 'antd';
import {
  ArrowLeftOutlined,
  ShoppingCartOutlined,
  StarOutlined,
} from '@ant-design/icons';
import * as api from './api';
import type { ModelListing, ModelReview } from './types';

const { TextArea } = Input;

export const ModelDetail: React.FC = () => {
  const { modelId } = useParams<{ modelId: string }>();
  const navigate = useNavigate();
  const [model, setModel] = useState<ModelListing | null>(null);
  const [reviews, setReviews] = useState<ModelReview[]>([]);
  const [loading, setLoading] = useState(false);
  const [purchasing, setPurchasing] = useState(false);
  const [newRating, setNewRating] = useState(5);
  const [newComment, setNewComment] = useState('');
  const [submittingReview, setSubmittingReview] = useState(false);

  const CATEGORY_LABELS: Record<string, string> = {
    detect: '目标检测',
    segment: '语义分割',
    pose: '姿态估计',
    planning: '路径规划',
    gs: '3D Gaussian Splatting',
    llm: '大语言模型',
    vlm: '视觉语言模型',
    other: '其他',
  };

  const LICENSE_LABELS: Record<string, string> = {
    free: '免费',
    'one-time': '一次性购买',
    subscription: '订阅',
  };

  const LICENSE_COLORS: Record<string, string> = {
    free: 'green',
    'one-time': 'blue',
    subscription: 'orange',
  };

  const fetchModel = async () => {
    if (!modelId) return;
    setLoading(true);
    try {
      const data = await api.getModel(modelId);
      setModel(data);
    } catch (e) {
      message.error('加载模型失败');
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const fetchReviews = async () => {
    if (!modelId) return;
    try {
      const data = await api.listReviews(modelId);
      setReviews(data);
    } catch (e) {
      message.error('加载评论失败');
      console.error(e);
    }
  };

  useEffect(() => {
    if (modelId) {
      fetchModel();
      fetchReviews();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelId]);

  const handlePurchase = async () => {
    if (!model || !modelId) return;
    setPurchasing(true);
    try {
      const res = await api.purchaseModel(modelId);
      if (res.status === 'completed') {
        message.success('购买成功，现在可以下载模型了');
      } else {
        message.info('购买已提交，请等待平台确认付款');
      }
      fetchModel();
    } catch (e) {
      message.error('购买失败');
      console.error(e);
    } finally {
      setPurchasing(false);
    }
  };

  const handleSubmitReview = async () => {
    if (!model || !modelId) return;
    setSubmittingReview(true);
    try {
      await api.createReview(modelId, { rating: newRating, comment: newComment });
      message.success('评论提交成功');
      setNewComment('');
      setNewRating(5);
      fetchReviews();
      fetchModel();
    } catch (e) {
      message.error('提交失败');
      console.error(e);
    } finally {
      setSubmittingReview(false);
    }
  };

  const formatPrice = (cents?: number) => {
    if (cents == null || cents === 0) return '免费';
    return `¥${(cents / 100).toFixed(2)}`;
  };

  if (!model) {
    return (
      <div style={{ padding: 24 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/model-marketplace')}>
          返回列表
        </Button>
        <div style={{ marginTop: 24 }}>{loading ? '加载中...' : '模型不存在'}</div>
      </div>
    );
  }

  return (
    <div style={{ padding: 16, maxWidth: 900, margin: '0 auto' }}>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/model-marketplace')}>
          返回列表
        </Button>
      </Space>

      <Card>
        <Space direction="vertical" style={{ width: '100%' }} size="small">
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {!model.published && <Tag color="gray">草稿</Tag>}
            <Tag color={LICENSE_COLORS[model.licenseType] || 'gray'}>
              {LICENSE_LABELS[model.licenseType] || model.licenseType}
            </Tag>
            <Tag>{CATEGORY_LABELS[model.category] || model.category}</Tag>
            {model.tags?.map(t => <Tag key={t}>{t}</Tag>)}
          </div>
          <h1>{model.name}</h1>
          <Space size="large">
            {model.averageRating && (
              <Space>
                <Rate disabled allowHalf value={model.averageRating} />
                <span>({model.reviewCount} 评价)</span>
              </Space>
            )}
            <span style={{ color: 'rgba(0,0,0,0.45)' }}>
              <StarOutlined /> {model.purchaseCount} 已购买
            </span>
          </Space>
        </Space>

        <Divider />

        <div style={{ display: 'flex', gap: 32, flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: 280 }}>
            <h3>模型描述</h3>
            <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.8 }}>
              {model.description}
            </div>
          </div>
          <div style={{ width: 220 }}>
            <Card size="small">
              <Statistic
                title="价格"
                value={formatPrice(model.priceCents)}
                valueStyle={{ fontSize: 24 }}
              />
              <Divider />
              <div style={{ fontSize: 13, color: 'rgba(0,0,0,0.65)', marginBottom: 16 }}>
                作者分成 {model.revenueSplitAuthor}%
              </div>
              <Button
                type="primary"
                size="large"
                block
                icon={<ShoppingCartOutlined />}
                onClick={handlePurchase}
                loading={purchasing}
                disabled={model.licenseType === 'free' && model.priceCents === 0 && model.published}
              >
                {model.licenseType === 'free' ? '免费获取' : '立即购买'}
              </Button>
            </Card>
          </div>
        </div>
      </Card>

      {!model.published && (
        <Alert
          style={{ marginTop: 16 }}
          status="warning"
          message="此模型当前为草稿状态，仅作者可见，未公开"
        />
      )}

      <Divider />

      <div>
        <h3>用户评价 ({reviews.length})</h3>

        <Card size="small" style={{ marginBottom: 16 }}>
          <Form.Item label="评分">
            <Rate value={newRating} onChange={setNewRating} />
          </Form.Item>
          <Form.Item label="评论">
            <TextArea
              rows={3}
              placeholder="分享你的使用体验..."
              value={newComment}
              onChange={e => setNewComment(e.target.value)}
            />
          </Form.Item>
          <div style={{ textAlign: 'right' }}>
            <Button
              type="primary"
              onClick={handleSubmitReview}
              loading={submittingReview}
            >
              提交评价
            </Button>
          </div>
        </Card>

        <List
          dataSource={reviews}
          renderItem={(item) => (
            <Comment
              author={`用户 ${item.userId?.slice(0, 8)}`}
              avatar={<Avatar>{item.userId?.[0]?.toUpperCase() ?? 'U'}</Avatar>}
              content={
                <div>
                  <Rate disabled value={item.rating} style={{ fontSize: 14, marginBottom: 8 }} />
                  {item.comment && <p>{item.comment}</p>}
                </div>
              }
              datetime={
                <span>{new Date(item.createdAt).toLocaleString()}</span>
              }
            />
          )}
        />
      </div>
    </div>
  );
};
