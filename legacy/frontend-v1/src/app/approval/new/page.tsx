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
  InputNumber,
  message,
  Typography,
  Alert,
  Divider,
} from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import * as cityApi from '../../../../approval/api';
import type { CityTemplate } from '../../../../approval/types';

const { Title, Text } = Typography;
const { Option } = Select;

// Top provinces for quick selection
const PROVINCES = [
  '北京市', '上海市', '广东省', '江苏省', '浙江省',
  '山东省', '四川省', '湖北省', '河南省', '湖南省',
  '河北省', '福建省', '云南省', '辽宁省', '黑龙江省',
  '安徽省', '江西省', '广西壮族自治区', '贵州省', '海南省',
  '重庆市', '陕西省', '甘肃省', '青海省', '宁夏回族自治区',
  '新疆维吾尔自治区', '内蒙古自治区', '西藏自治区', '吉林省',
];

export default function NewApprovalPage() {
  const navigate = useNavigate();
  const [form] = Form.useForm();
  const [templates, setTemplates] = useState<CityTemplate[]>([]);
  const [selectedProvince, setSelectedProvince] = useState<string>();
  const [selectedCity, setSelectedCity] = useState<string>();
  const [currentTemplate, setCurrentTemplate] = useState<CityTemplate | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchTemplates = async (province?: string) => {
    setLoading(true);
    try {
      const data = await cityApi.listCityTemplates(province);
      setTemplates(data);
    } catch (e) {
      message.error('加载城市模板失败');
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  // Initial fetch all templates
  useEffect(() => {
    fetchTemplates();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onProvinceChange = (province: string) => {
    setSelectedProvince(province);
    fetchTemplates(province);
    setSelectedCity(undefined);
    setCurrentTemplate(null);
  };

  const onCityChange = async (city: string) => {
    setSelectedCity(city);
    if (!selectedProvince) return;
    try {
      const tpl = await cityApi.getCityTemplate(selectedProvince, city);
      setCurrentTemplate(tpl);
      // Reset form when template changes
      form.resetFields();
    } catch (e) {
      message.error('加载城市模板失败');
      console.error(e);
      setCurrentTemplate(null);
    }
  };

  const getLabel = (field: string): string => {
    if (currentTemplate?.fieldLabels?.[field]) {
      return currentTemplate.fieldLabels[field];
    }
    // Default labels
    const defaults: Record<string, string> = {
      organizer: '主办单位',
      contact: '联系人及电话',
      drone_count: '无人机数量及型号',
      flight_date: '飞行起止时间',
      flight_area: '飞行范围',
      purpose: '飞行目的',
      work_altitude: '作业高度',
      insurance: '第三者责任险',
      pilot_name: '飞行员姓名',
      pilot_license: '飞行员执照编号',
      aircraft_reg: '无人机注册号',
      aircraft_model: '无人机型号',
    };
    return defaults[field] || field;
  };

  const handleSubmit = async (values: any) => {
    // TODO: create flight approval with dynamic fields
    console.log('submit', values);
    message.success('创建成功');
    navigate('/approval');
  };

  return (
    <div style={{ padding: 16, maxWidth: 800, margin: '0 auto' }}>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/approval')}>
          返回列表
        </Button>
      </Space>

      <Card>
        <Form
          form={form}
          layout="vertical"
          onFinish={handleSubmit}
        >
          <Title level={4}>选择城市</Title>
          <Space direction="horizontal" size="large" style={{ marginBottom: 24 }}>
            <Form.Item label="省份" name="province" style={{ minWidth: 200 }}>
              <Select
                placeholder="选择省份"
                allowClear
                onChange={onProvinceChange}
                value={selectedProvince}
              >
                {PROVINCES.map(p => (
                  <Option key={p} value={p}>{p}</Option>
                ))}
              </Select>
            </Form.Item>
            <Form.Item label="城市" name="city" style={{ minWidth: 200 }}>
              <Select
                placeholder="选择城市"
                allowClear
                onChange={onCityChange}
                value={selectedCity}
                loading={loading}
              >
                {templates.map(t => (
                  <Option key={t.city} value={t.city}>{t.city}</Option>
                ))}
              </Select>
            </Form.Item>
          </Space>

          {currentTemplate && (
            <>
              <Divider />
              <Title level={4}>填写报备信息</Title>

              <Alert
                message={`${currentTemplate.province}${currentTemplate.city}报备要求`}
                description={`本${currentTemplate.submissionChannel === 'email' ? '市采用邮件报备，系统会自动生成符合要求的邮件。' : currentTemplate.submissionChannel === 'online-rpa' ? '系统会自动在线提交报备。' : '请按要求填写后下载表格手动提交。'}`}
                type="info"
                style={{ marginBottom: 24 }}
              />

              {currentTemplate.requiredFields.map(field => (
                <Form.Item
                  key={field}
                  name={field}
                  label={getLabel(field)}
                  rules={[{ required: true, message: '请填写此字段' }]}
                >
                  {field.includes('date') ? (
                    <DatePicker.RangePicker showTime />
                  ) : field.includes('count') || field.includes('altitude') ? (
                    <InputNumber min={0} style={{ width: 200 }} />
                  ) : (
                    <Input placeholder={getLabel(field)} />
                  )}
                </Form.Item>
              ))}

              <Divider />

              <Space style={{ justifyContent: 'flex-end' }}>
                <Button onClick={() => navigate('/approval')}>取消</Button>
                <Button type="primary" htmlType="submit">提交报备</Button>
              </Space>
            </>
          )}

          {!currentTemplate && selectedCity && (
            <Alert
              message="未找到该城市的报备模板"
              description="请联系管理员添加模板，或选择其他城市。"
              type="warning"
            />
          )}
        </Form>
      </Card>
    </div>
  );
}
