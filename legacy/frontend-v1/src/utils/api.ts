import axios from 'axios';

// 基础 API 配置
const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000',
  timeout: 30000,
  withCredentials: true,
});

// 请求拦截器：添加认证 token
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('skymaster_auth_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// 响应拦截器：统一错误处理
api.interceptors.response.use(
  (response) => {
    return response;
  },
  (error) => {
    if (error.response?.status === 401) {
      // 未授权，跳转到登录
      localStorage.removeItem('skymaster_auth_token');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export { api };
export default api;
