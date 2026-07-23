'use client';

import React, { useState, useEffect } from 'react';
import {
  Card,
  Button,
  Space,
  Form,
  Input,
  Select,
  DatePicker,
  message,
  Typography,
  Alert,
} from 'antd';
import { useNavigate } from 'react-router-dom';
import { PlusOutlined } from '@ant-design/icons';
import * as api from '../../../approval/api';
import type { CityTemplate } from '../../../approval/types';

const { Title, Text } = Typography;

// Top 30 provinces for quick selection
const PROVINCES = [
  '北京市', '上海市', '广东省', '江苏省', '浙江省',
  '山东省', '四川省', '湖北省', '河南省', '湖南省',
  '河北省', '福建省', '云南省', '辽宁省', '黑龙江省',
  '安徽省', '江西省', '广西壮族自治区', '贵州省', '海南省',
  '重庆市', '陕西省', '甘肃省', '青海省', '宁夏回族自治区',
  '新疆维吾尔自治区', '内蒙古自治区', '西藏自治区', '吉林省',
];

export default function ApprovalListPage() {
  const navigate = useNavigate();

  return (
    <div style={{ padding: 16, maxWidth: 1000, margin: '0 auto' }}>
      <Space direction="vertical" style={{ width: '100%' }} size="large">
        <Space>
          <h1>飞行报备</h1>
        </Space>
        <Card>
          <Space direction="vertical" style={{ width: '100%' }}>
            <Text>
              SkyMaster 支持全国多城市属地自动报备，根据您所在城市自动加载要求的表单。
              点击下方创建新的飞行报备申请。
            </Text>
            <div style={{ textAlign: 'center', padding: '24px 0' }}>
              <Button
                type="primary"
                size="large"
                icon={<PlusOutlined />}
                onClick={() => navigate('/approval/new')}
              >
                创建新报备
              </Button>
            </div>
          </Space>
        </Card>
      </Space>
    </div>
  );
}
