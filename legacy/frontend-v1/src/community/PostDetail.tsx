/**
 * Community Post Detail page with comments — SkyMaster v2.2 E4
 */
import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Card,
  Button,
  Space,
  Tag,
  Input,
  List,
  Comment,
  Form,
  message,
  Avatar,
  Alert,
  Divider,
} from 'antd';
import {
  LikeOutlined,
  LikeFilled,
  ArrowLeftOutlined,
} from '@ant-design/icons';
import * as api from './api';
import type { CommunityPost, CommunityComment as CommentType } from './types';

const { TextArea } = Input;

export const PostDetail: React.FC = () => {
  const { postId } = useParams<{ postId: string }>();
  const navigate = useNavigate();
  const [post, setPost] = useState<CommunityPost | null>(null);
  const [comments, setComments] = useState<CommentType[]>([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [newComment, setNewComment] = useState('');
  const [liked, setLiked] = useState(false);

  const fetchPost = async () => {
    if (!postId) return;
    setLoading(true);
    try {
      const data = await api.getPost(postId);
      setPost(data);
    } catch (e) {
      message.error('加载帖子失败');
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const fetchComments = async () => {
    if (!postId) return;
    try {
      const data = await api.listComments(postId);
      setComments(data.filter(c => c.moderationStatus === 'approved'));
    } catch (e) {
      message.error('加载评论失败');
      console.error(e);
    }
  };

  useEffect(() => {
    if (postId) {
      fetchPost();
      fetchComments();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [postId]);

  const handleLike = async () => {
    if (!post) return;
    try {
      if (!liked) {
        const res = await api.likePost(post.id);
        setPost({ ...post, likeCount: res.likeCount });
      } else {
        const res = await api.unlikePost(post.id);
        setPost({ ...post, likeCount: res.likeCount });
      }
      setLiked(!liked);
    } catch (e) {
      message.error('操作失败');
      console.error(e);
    }
  };

  const handleSubmitComment = async () => {
    if (!post || !postId || !newComment.trim()) return;
    setSubmitting(true);
    try {
      await api.addComment(postId, { body: newComment.trim() });
      message.success('评论已提交，审核通过后显示');
      setNewComment('');
      fetchComments();
    } catch (e) {
      message.error('提交失败');
      console.error(e);
    } finally {
      setSubmitting(false);
    }
  };

  const getModerationColor = (status: string) => {
    switch (status) {
      case 'approved': return 'green';
      case 'pending': return 'orange';
      case 'rejected': return 'red';
      default: return 'gray';
    }
  };

  if (!post) {
    return (
      <div style={{ padding: 24 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/community')}>
          返回列表
        </Button>
        <div style={{ marginTop: 24 }}>{loading ? '加载中...' : '帖子不存在'}</div>
      </div>
    );
  }

  return (
    <div style={{ padding: 16, maxWidth: 900, margin: '0 auto' }}>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/community')}>
          返回列表
        </Button>
      </Space>

      <Card>
        <Space direction="vertical" style={{ width: '100%' }} size="small">
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {post.pinned && <Tag color="blue">置顶</Tag>}
            <Tag color={getModerationColor(post.moderationStatus)}>
              {post.moderationStatus === 'approved' && '已通过'}
              {post.moderationStatus === 'pending' && '待审核'}
              {post.moderationStatus === 'rejected' && '已拒绝'}
            </Tag>
            {post.tags?.map(t => <Tag key={t}>{t}</Tag>)}
          </div>
          <h1>{post.title}</h1>
          <div style={{ color: 'rgba(0,0,0,0.45)', fontSize: 13 }}>
            <Space>
              <span>👁 {post.viewCount}</span>
              <span>💬 {post.commentCount}</span>
              <span>{new Date(post.createdAt).toLocaleString()}</span>
            </Space>
          </div>
        </Space>

        <Divider />

        <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.8, fontSize: 16 }}>
          {post.body}
        </div>

        <Divider />

        <div>
          <Button
            type={liked ? 'primary' : 'default'}
            icon={liked ? <LikeFilled /> : <LikeOutlined />}
            onClick={handleLike}
          >
            {post.likeCount} 点赞
          </Button>
        </div>
      </Card>

      {post.moderationStatus !== 'approved' && (
        <Alert
          style={{ marginTop: 16 }}
          status={post.moderationStatus === 'pending' ? 'warning' : 'error'}
          message={
            post.moderationStatus === 'pending'
              ? '此帖子正在审核中，仅作者可见，审核通过后公开'
              : '此帖子已被管理员拒绝，不会公开显示'
          }
        />
      )}

      <Divider />

      <div>
        <h3>评论 ({comments.length})</h3>

        {post.moderationStatus === 'approved' && (
          <Card size="small" style={{ marginBottom: 16 }}>
            <Form.Item>
              <TextArea
                rows={3}
                placeholder="发表你的评论..."
                value={newComment}
                onChange={e => setNewComment(e.target.value)}
              />
            </Form.Item>
            <div style={{ textAlign: 'right' }}>
              <Button
                type="primary"
                onClick={handleSubmitComment}
                loading={submitting}
                disabled={!newComment.trim()}
              >
                提交评论
              </Button>
            </div>
          </Card>
        )}

        <List
          dataSource={comments}
          loading={loading}
          renderItem={(item) => (
            <Comment
              author={`用户 ${item.authorId?.slice(0, 8)}`}
              avatar={<Avatar>{item.authorId?.[0]?.toUpperCase() ?? 'U'}</Avatar>}
              content={item.body}
              datetime={
                <span>{new Date(item.createdAt).toLocaleString()}</span>
              }
              actions={[
                <span key="like">
                  <LikeOutlined /> {item.likeCount}
                </span>
              ]}
            />
          )}
        />
      </div>
    </div>
  );
};
