# SkyMaster 部署指南

## 目录

- [系统要求](#系统要求)
- [快速部署](#快速部署)
- [Docker部署](#docker部署)
- [手动部署](#手动部署)
- [生产环境部署](#生产环境部署)
- [环境变量配置](#环境变量配置)
- [数据库配置](#数据库配置)
- [监控配置](#监控配置)
- [故障排查](#故障排查)
- [备份恢复](#备份恢复)

---

## 系统要求

### 硬件要求

#### 最低配置（开发/测试）
- **CPU**: 4核
- **内存**: 8GB
- **存储**: 50GB SSD
- **网络**: 100Mbps

#### 推荐配置（生产环境）
- **CPU**: 8核或以上
- **内存**: 16GB或以上
- **存储**: 200GB SSD（支持IOPS > 3000）
- **网络**: 1Gbps

### 软件要求

#### 操作系统
- Ubuntu 20.04 LTS 或更新版本
- CentOS 7/8
- Debian 10 或更新版本
- macOS 10.15+（开发环境）

#### 必需软件
- **Docker**: 20.10+
- **Docker Compose**: 2.0+
- **Git**: 2.30+
- **curl/wget**: 用于下载文件

#### 可选软件
- **Kubernetes**: 1.20+（云原生部署）
- **Helm**: 3.0+（Kubernetes包管理）
- **Terraform**: 1.0+（基础设施即代码）

---

## 快速部署

### 使用Docker Compose（推荐）

```bash
# 1. 克隆项目
git clone https://github.com/your-org/skymaster-drone-platform.git
cd skymaster-drone-platform

# 2. 配置环境变量
cp .env.example .env
nano .env  # 编辑配置文件

# 3. 启动所有服务
cd docker
docker-compose up -d

# 4. 查看服务状态
docker-compose ps

# 5. 查看日志
docker-compose logs -f backend

# 6. 访问应用
# 前端: http://localhost
# API文档: http://localhost:8000/docs
# Grafana: http://localhost:3000 (admin/admin)
```

### 验证部署

```bash
# 检查API健康状态
curl http://localhost:8000/health

# 预期输出
{
  "status": "healthy",
  "timestamp": "2026-03-11T12:00:00Z",
  "version": "1.0.0"
}
```

---

## Docker部署

### Docker镜像构建

#### 构建后端镜像

```bash
cd backend

# 构建镜像
docker build -t skymaster-backend:latest .

# 多阶段构建（优化镜像大小）
docker build -t skymaster-backend:alpine -f Dockerfile.alpine .
```

#### 构建前端镜像

```bash
cd frontend

# 构建生产镜像
docker build -t skymaster-frontend:latest .
```

### Docker Compose配置详解

#### 完整配置示例

```yaml
version: '3.8'

services:
  # 后端API服务
  backend:
    image: skymaster-backend:latest
    container_name: skymaster-backend
    restart: unless-stopped
    environment:
      - ENVIRONMENT=production
      - DATABASE_URL=postgresql://skymaster:${DB_PASSWORD}@postgres:5432/skymaster
      - REDIS_URL=redis://redis:6379/0
      - SECRET_KEY=${SECRET_KEY}
      - JWT_SECRET_KEY=${JWT_SECRET_KEY}
    volumes:
      - ./uploads:/app/uploads
      - ./logs:/app/logs
    ports:
      - "8000:8000"
    depends_on:
      - postgres
      - redis
    networks:
      - skymaster-network
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

  # 前端服务
  frontend:
    image: skymaster-frontend:latest
    container_name: skymaster-frontend
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ssl:/etc/nginx/ssl:ro
    depends_on:
      - backend
    networks:
      - skymaster-network

  # PostgreSQL数据库
  postgres:
    image: postgres:13-alpine
    container_name: skymaster-postgres
    restart: unless-stopped
    environment:
      - POSTGRES_USER=skymaster
      - POSTGRES_PASSWORD=${DB_PASSWORD}
      - POSTGRES_DB=skymaster
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./init-db.sql:/docker-entrypoint-initdb.d/init-db.sql:ro
    ports:
      - "5432:5432"
    networks:
      - skymaster-network
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U skymaster"]
      interval: 10s
      timeout: 5s
      retries: 5

  # Redis缓存
  redis:
    image: redis:6-alpine
    container_name: skymaster-redis
    restart: unless-stopped
    command: redis-server --appendonly yes --requirepass ${REDIS_PASSWORD}
    volumes:
      - redis_data:/data
    ports:
      - "6379:6379"
    networks:
      - skymaster-network
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5

networks:
  skymaster-network:
    driver: bridge

volumes:
  postgres_data:
  redis_data:
```

### 容器管理命令

```bash
# 启动服务
docker-compose up -d

# 停止服务
docker-compose down

# 重启服务
docker-compose restart

# 查看日志
docker-compose logs -f [service_name]

# 进入容器
docker-compose exec backend bash

# 查看资源使用
docker stats

# 清理无用资源
docker system prune -a
```

---

## 手动部署

### 后端部署

#### 1. 安装Python环境

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install -y python3.9 python3.9-venv python3-pip

# CentOS/RHEL
sudo yum install -y python39 python39-pip
```

#### 2. 创建虚拟环境

```bash
cd backend
python3.9 -m venv venv
source venv/bin/activate  # Linux/macOS
# 或 venv\Scripts\activate  # Windows
```

#### 3. 安装依赖

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

#### 4. 配置环境变量

```bash
# 创建.env文件
cat > .env << EOF
ENVIRONMENT=production
DATABASE_URL=postgresql://skymaster:password@localhost:5432/skymaster
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=$(openssl rand -hex 32)
JWT_SECRET_KEY=$(openssl rand -hex 32)
EOF
```

#### 5. 数据库迁移

```bash
# 运行迁移
alembic upgrade head

# 创建管理员用户
python scripts/create_admin.py
```

#### 6. 启动服务

```bash
# 使用Gunicorn（生产环境）
gunicorn api.v1.main:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --access-logfile logs/access.log \
  --error-logfile logs/error.log \
  --log-level info

# 或使用Uvicorn（开发环境）
uvicorn api.v1.main:app --host 0.0.0.0 --port 8000 --reload
```

#### 7. 使用Systemd管理服务

```bash
# 创建服务文件
sudo nano /etc/systemd/system/skymaster-backend.service
```

```ini
[Unit]
Description=SkyMaster Backend API
After=network.target postgresql.service redis.service

[Service]
Type=notify
User=skymaster
Group=skymaster
WorkingDirectory=/opt/skymaster/backend
Environment="PATH=/opt/skymaster/backend/venv/bin"
ExecStart=/opt/skymaster/backend/venv/bin/gunicorn \
  api.v1.main:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# 启动服务
sudo systemctl daemon-reload
sudo systemctl enable skymaster-backend
sudo systemctl start skymaster-backend
sudo systemctl status skymaster-backend
```

### 前端部署

#### 1. 安装Node.js

```bash
# Ubuntu/Debian
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs

# 或使用nvm
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash
nvm install 18
nvm use 18
```

#### 2. 安装依赖

```bash
cd frontend
npm install
```

#### 3. 配置环境变量

```bash
# 创建.env.production
cat > .env.production << EOF
NEXT_PUBLIC_API_URL=https://api.skymaster.io
NEXT_PUBLIC_WS_URL=wss://api.skymaster.io/ws
NEXT_PUBLIC_MAP_TOKEN=your-map-token
EOF
```

#### 4. 构建生产版本

```bash
npm run build
```

#### 5. 启动服务

```bash
# 使用PM2管理
npm install -g pm2
pm2 start npm --name "skymaster-frontend" -- start
pm2 save
pm2 startup
```

---

## 生产环境部署

### Nginx配置

```nginx
# /etc/nginx/sites-available/skymaster.conf

# 后端API
upstream backend {
    least_conn;
    server 127.0.0.1:8001;
    server 127.0.0.1:8002;
    server 127.0.0.1:8003;
}

# HTTP服务器
server {
    listen 80;
    server_name skymaster.io www.skymaster.io;
    
    # 重定向到HTTPS
    return 301 https://$server_name$request_uri;
}

# HTTPS服务器
server {
    listen 443 ssl http2;
    server_name skymaster.io www.skymaster.io;
    
    # SSL配置
    ssl_certificate /etc/letsencrypt/live/skymaster.io/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/skymaster.io/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    
    # 安全头
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    
    # 前端静态文件
    location / {
        root /opt/skymaster/frontend/dist;
        try_files $uri $uri/ /index.html;
        
        # 缓存静态资源
        location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
            expires 1y;
            add_header Cache-Control "public, immutable";
        }
    }
    
    # API代理
    location /api/ {
        proxy_pass http://backend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # 超时设置
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
    
    # WebSocket代理
    location /ws {
        proxy_pass http://backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket超时
        proxy_connect_timeout 7d;
        proxy_send_timeout 7d;
        proxy_read_timeout 7d;
    }
    
    # 视频流代理
    location /stream/ {
        proxy_pass http://localhost:8080/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
    
    # Gzip压缩
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_types text/plain text/css text/xml text/javascript application/x-javascript application/xml application/javascript application/json;
    
    # 日志
    access_log /var/log/nginx/skymaster_access.log;
    error_log /var/log/nginx/skymaster_error.log;
}
```

### SSL证书配置

```bash
# 使用Let's Encrypt
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d skymaster.io -d www.skymaster.io

# 自动续期
sudo crontab -e
# 添加以下行
0 12 * * * /usr/bin/certbot renew --quiet
```

---

## 环境变量配置

### 完整环境变量列表

```bash
# .env.example

# ========== 应用配置 ==========
ENVIRONMENT=production
APP_NAME=SkyMaster Drone Platform
APP_VERSION=1.0.0
DEBUG=false

# ========== API配置 ==========
API_HOST=0.0.0.0
API_PORT=8000
API_PREFIX=/api/v1

# ========== 数据库配置 ==========
DATABASE_URL=postgresql://skymaster:password@postgres:5432/skymaster
DATABASE_POOL_SIZE=20
DATABASE_MAX_OVERFLOW=40

# ========== Redis配置 ==========
REDIS_URL=redis://redis:6379/0
REDIS_PASSWORD=your_redis_password

# ========== 安全配置 ==========
SECRET_KEY=your-secret-key-min-32-characters-long
JWT_SECRET_KEY=your-jwt-secret-key-min-32-characters
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60

# ========== CORS配置 ==========
CORS_ORIGINS=https://skymaster.io,https://www.skymaster.io
CORS_ALLOW_CREDENTIALS=true

# ========== MAVLink配置 ==========
MAVLINK_DEFAULT_BAUD_RATE=57600
MAVLINK_TIMEOUT=5.0
MAVLINK_HEARTBEAT_INTERVAL=1.0

# ========== 设备配置 ==========
DEVICE_MAX_CONNECTIONS=100
DEVICE_OFFLINE_TIMEOUT=10.0

# ========== WebSocket配置 ==========
WS_HEARTBEAT_INTERVAL=30.0
WS_MAX_CONNECTIONS=1000

# ========== 视频流配置 ==========
VIDEO_STREAM_ENABLED=true
VIDEO_STREAM_RTSP_PORT=8554
VIDEO_STREAM_WEBRTC_PORT=8080

# ========== 飞行限制 ==========
MAX_FLIGHT_ALTITUDE=120.0
MAX_FLIGHT_DISTANCE=5000.0
MAX_FLIGHT_SPEED=15.0

# ========== 电池保护 ==========
BATTERY_LOW_THRESHOLD=20
BATTERY_CRITICAL_THRESHOLD=10

# ========== 日志配置 ==========
LOG_LEVEL=INFO
LOG_FILE=logs/skymaster.log
LOG_MAX_SIZE=10485760
LOG_BACKUP_COUNT=5

# ========== Celery配置 ==========
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2

# ========== 集群配置 ==========
SWARM_MAX_SIZE=20
SWARM_MIN_SEPARATION=5.0
SWARM_SYNC_TOLERANCE=2.0

# ========== 任务配置 ==========
MISSION_MAX_WAYPOINTS=1000
MISSION_AUTO_SAVE=true

# ========== 地图配置 ==========
CESIUM_ION_TOKEN=your-cesium-ion-token
MAP_DEFAULT_LATITUDE=39.9042
MAP_DEFAULT_LONGITUDE=116.4074
MAP_DEFAULT_ZOOM=15

# ========== 文件存储 ==========
UPLOAD_DIR=uploads
MAX_UPLOAD_SIZE=104857600

# ========== 第三方服务 ==========
DJI_SDK_APP_ID=your-dji-app-id
DJI_SDK_APP_KEY=your-dji-app-key

# ========== 监控配置 ==========
PROMETHEUS_ENABLED=true
GRAFANA_ADMIN_PASSWORD=admin

# ========== 邮件配置 ==========
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-email-password
SMTP_FROM=noreply@skymaster.io
```

---

## 数据库配置

### PostgreSQL优化

```sql
-- /etc/postgresql/13/main/postgresql.conf

-- 连接设置
max_connections = 200
superuser_reserved_connections = 5

-- 内存设置
shared_buffers = 4GB
effective_cache_size = 12GB
maintenance_work_mem = 1GB
work_mem = 64MB

-- WAL设置
wal_buffers = 16MB
checkpoint_completion_target = 0.9
max_wal_size = 2GB

-- 查询优化
random_page_cost = 1.1
effective_io_concurrency = 200
default_statistics_target = 100

-- 日志设置
logging_collector = on
log_directory = 'pg_log'
log_filename = 'postgresql-%Y-%m-%d_%H%M%S.log'
log_statement = 'ddl'
log_min_duration_statement = 1000
```

### TimescaleDB配置

```sql
-- 启用TimescaleDB
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- 创建遥测数据表
CREATE TABLE telemetry (
    time            TIMESTAMPTZ NOT NULL,
    device_id       VARCHAR(50) NOT NULL,
    latitude        DOUBLE PRECISION,
    longitude       DOUBLE PRECISION,
    altitude        DOUBLE PRECISION,
    speed           DOUBLE PRECISION,
    battery         INTEGER,
    flight_mode     VARCHAR(50),
    armed           BOOLEAN
);

-- 转换为超表
SELECT create_hypertable('telemetry', 'time', chunk_time_interval => INTERVAL '1 day');

-- 创建索引
CREATE INDEX idx_telemetry_device_time ON telemetry (device_id, time DESC);

-- 设置压缩
ALTER TABLE telemetry SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'device_id'
);

-- 自动压缩策略（7天后）
SELECT add_compression_policy('telemetry', INTERVAL '7 days');

-- 自动删除策略（90天后）
SELECT add_retention_policy('telemetry', INTERVAL '90 days');
```

---

## 监控配置

### Prometheus配置

```yaml
# prometheus.yml

global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  # Prometheus自身
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  # SkyMaster后端
  - job_name: 'skymaster-backend'
    static_configs:
      - targets: ['backend:8000']
    metrics_path: '/metrics'

  # PostgreSQL
  - job_name: 'postgres'
    static_configs:
      - targets: ['postgres-exporter:9187']

  # Redis
  - job_name: 'redis'
    static_configs:
      - targets: ['redis-exporter:9121']

  # Node Exporter
  - job_name: 'node'
    static_configs:
      - targets: ['node-exporter:9100']

  # cAdvisor (容器监控)
  - job_name: 'cadvisor'
    static_configs:
      - targets: ['cadvisor:8080']
```

### Grafana Dashboard

```json
{
  "dashboard": {
    "title": "SkyMaster Monitoring",
    "panels": [
      {
        "title": "API Request Rate",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(http_requests_total[5m])"
          }
        ]
      },
      {
        "title": "Active Devices",
        "type": "stat",
        "targets": [
          {
            "expr": "skymaster_devices_online"
          }
        ]
      },
      {
        "title": "WebSocket Connections",
        "type": "gauge",
        "targets": [
          {
            "expr": "skymaster_websocket_connections"
          }
        ]
      }
    ]
  }
}
```

---

## 故障排查

### 常见问题

#### 1. 数据库连接失败

```bash
# 检查数据库状态
docker-compose ps postgres

# 查看日志
docker-compose logs postgres

# 测试连接
psql -h localhost -U skymaster -d skymaster

# 解决方案
# 1. 检查数据库配置
# 2. 确认密码正确
# 3. 检查网络连接
```

#### 2. Redis连接失败

```bash
# 测试Redis连接
redis-cli -h localhost -p 6379 ping

# 如果设置了密码
redis-cli -h localhost -p 6379 -a your_password ping
```

#### 3. 后端服务无法启动

```bash
# 查看详细日志
docker-compose logs backend

# 常见原因
# 1. 环境变量未配置
# 2. 依赖服务未启动
# 3. 端口被占用
# 4. 权限问题

# 检查端口占用
sudo netstat -tulpn | grep :8000
```

#### 4. WebSocket连接失败

```bash
# 检查Nginx配置
sudo nginx -t

# 查看Nginx错误日志
sudo tail -f /var/log/nginx/error.log

# 确认WebSocket升级头配置正确
```

#### 5. 视频流无法播放

```bash
# 检查RTSP服务器
docker-compose logs mediamtx

# 测试RTSP流
ffplay rtsp://localhost:8554/stream

# 检查WebRTC服务
docker-compose logs webrtc-signaling
```

### 日志查看

```bash
# 查看所有服务日志
docker-compose logs -f

# 查看特定服务日志
docker-compose logs -f backend

# 查看最近100行
docker-compose logs --tail=100 backend

# 导出日志
docker-compose logs > logs.txt
```

---

## 备份恢复

### 数据库备份

```bash
# 手动备份
docker-compose exec postgres pg_dump -U skymaster skymaster > backup_$(date +%Y%m%d).sql

# 自动备份脚本
cat > /opt/skymaster/backup.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="/opt/skymaster/backups"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/skymaster_$DATE.sql"

# 创建备份目录
mkdir -p $BACKUP_DIR

# 执行备份
docker-compose exec -T postgres pg_dump -U skymaster skymaster > $BACKUP_FILE

# 压缩备份
gzip $BACKUP_FILE

# 删除30天前的备份
find $BACKUP_DIR -name "*.sql.gz" -mtime +30 -delete

echo "Backup completed: $BACKUP_FILE.gz"
EOF

chmod +x /opt/skymaster/backup.sh

# 添加到crontab（每天凌晨2点）
crontab -e
0 2 * * * /opt/skymaster/backup.sh >> /opt/skymaster/logs/backup.log 2>&1
```

### 数据库恢复

```bash
# 恢复数据库
gunzip -c skymaster_20260311.sql.gz | docker-compose exec -T postgres psql -U skymaster skymaster
```

### Redis备份

```bash
# Redis自动备份（RDB）
# redis.conf
save 900 1
save 300 10
save 60 10000

# 手动触发备份
docker-compose exec redis redis-cli BGSAVE

# 复制RDB文件
docker cp skymaster-redis:/data/dump.rdb ./redis_backup_$(date +%Y%m%d).rdb
```

---

## 升级指南

### 版本升级步骤

```bash
# 1. 备份数据
/opt/skymaster/backup.sh

# 2. 拉取最新代码
git pull origin main

# 3. 查看变更
git log --oneline -10

# 4. 停止服务
docker-compose down

# 5. 更新镜像
docker-compose pull

# 6. 运行数据库迁移
docker-compose run backend alembic upgrade head

# 7. 启动服务
docker-compose up -d

# 8. 验证服务
curl http://localhost:8000/health

# 9. 查看日志
docker-compose logs -f
```

---

## 安全加固

### 防火墙配置

```bash
# Ubuntu UFW
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable

# 限制数据库访问
sudo ufw deny 5432
sudo ufw deny 6379
```

### 安全检查清单

- [ ] 更改默认密码
- [ ] 启用HTTPS
- [ ] 配置防火墙规则
- [ ] 定期更新系统补丁
- [ ] 启用日志审计
- [ ] 配置备份策略
- [ ] 限制API访问速率
- [ ] 启用CORS白名单
- [ ] 定期安全扫描

---

**文档版本**: 1.0.0  
**最后更新**: 2026-03-11  
**维护者**: SkyMaster运维团队
