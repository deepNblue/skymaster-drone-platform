/**
 * Community Post List page — SkyMaster v2.2 E4
 */
import React, { useState, useEffect } from 'react';
import {
  Card,
  Button,
  Space,
  Tag,
  Input,
  Pagination,
  Modal,
  Form,
  message,
  Popconfirm,
  Badge,
} from 'antd';
import {
  PlusOutlined,
  EyeOutlined,
  EditOutlined,
  DeleteOutlined,
  LikeOutlined,
  CommentOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import * as api from './api';
import type { CommunityPost, CreatePostRequest } from './types';

const { TextArea } = Input;

export const PostList: React.FC = () => {
  const navigate = useNavigate();
  const [posts, setPosts] = useState<CommunityPost[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(false);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [form] = Form.useForm<CreatePostRequest>();

  const fetchPosts = async () => {
    setLoading(true);
    try {
      const res = await api.listPosts({ page, size: pageSize });
      setPosts(res.items);
      setTotal(res.total);
    } catch (e) {
      message.error('加载帖子列表失败');
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPosts();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize]);

  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      await api.createPost(values);
      message.success('发布成功，等待审核');
      setCreateModalOpen(false);
      form.resetFields();
      fetchPosts();
    } catch (e) {
      message.error('发布失败');
      console.error(e);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await api.deletePost(id);
      message.success('删除成功');
      fetchPosts();
    } catch (e) {
      message.error('删除失败');
      console.error(e);
    }
  };

  const getModerationTagColor = (status: string) => {
    switch (status) {
      case 'approved':
        return 'green';
      case 'pending':
        return 'orange';
      case 'rejected':
        return 'red';
      default:
        return 'gray';
    }
  };

  const getModerationTagText = (status: string) => {
    switch (status) {
      case 'approved':
        return '已通过';
      case 'pending':
        return '待审核';
      case 'rejected':
        return '已拒绝';
      default:
        return status;
    }
  };

  return (
    <div style={{ padding: 16, maxWidth: 960, margin: '0 auto' }}>
      <Space style={{ marginBottom: 16 }} direction="vertical" style={{ width: '100%' }}>
        <Space>
          <h1>社区讨论</h1>
        </Space>
        <Space style={{ justifyContent: 'flex-end' }}>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setCreateModalOpen(true)}
          >
            发布新帖
          </Button>
        </Space>
      </Space>

      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        {posts.map((post) => (
          <Card
            key={post.id}
            hoverable
            onClick={() => navigate(`/community/posts/${post.id}`)}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start' }}>
              <div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
                  {post.pinned && <Badge status="processing" text="置顶" />}
                  <Tag color={getModerationTagColor(post.moderationStatus)}>
                    {getModerationTagText(post.moderationStatus)}
                  </Tag>
                  {post.tags?.map((t) => (
                    <Tag key={t}>{t}</Tag>
                  ))}
                </div>
                <h3 style={{ margin: 0 }}>{post.title}</h3>
              </div>
              <Space>
                <Button
                  icon={<EyeOutlined />}
                  size="small"
                  onClick={(e) => {
                    e.stopPropagation();
                    navigate(`/community/posts/${post.id}`);
                  }}
                >
                  查看
                </Button>
                <Button
                  icon={<EditOutlined />}
                  size="small"
                  onClick={(e) => {
                    e.stopPropagation();
                    navigate(`/community/posts/${post.id}/edit`);
                  }}
                />
                <Popconfirm
                  title="确定删除此帖子吗？"
                  onCancel={(e) => e?.stopPropagation()}
                  onConfirm={(e) => {
                    e?.stopPropagation();
                    handleDelete(post.id);
                  }}
                >
                  <Button
                    danger
                    icon={<DeleteOutlined />}
                    size="small"
                    onClick={(e) => e.stopPropagation()}
                  />
                </Popconfirm>
              </Space>
            </div>

            <div style={{ marginTop: 12, color: 'rgba(0, 0, 0, 0.45)', fontSize: 13 }}>
              <Space size="middle">
                <span><LikeOutlined /> {post.likeCount}</span>
                <span><CommentOutlined /> {post.commentCount}</span>
                <span>👁 {post.viewCount}</span>
                <span>{new Date(post.createdAt).toLocaleString()}</span>
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
        title="发布新帖子"
        open={createModalOpen}
        onCancel={() => setCreateModalOpen(false)}
        onOk={handleCreate}
        okText="发布"
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="title"
            label="标题"
            rules={[{ required: true, min: 5, max: 255 }]}
          >
            <Input placeholder="请输入帖子标题" />
          </Form.Item>
          <Form.Item
            name="body"
            label="内容"
            rules={[{ required: true, min: 10 }]}
          >
            <TextArea
              rows={8}
              placeholder="请输入帖子内容..."
            />
          </Form.Item>
          <Form.Item
            name="tags"
            label="标签"
            help="用逗号分隔多个标签"
          >
            <Input placeholder="无人机,测绘,经验分享" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};
