# SkyMaster - 智能无人机管控平台

<div align="center">

![SkyMaster Logo](docs/images/logo.png)

**企业级无人机集群管控解决方案**

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)
[![React](https://img.shields.io/badge/react-18+-blue.svg)](https://reactjs.org/)
[![FastAPI](https://img.shields.io/badge/fastapi-0.100+-green.svg)](https://fastapi.tiangolo.com/)

[在线演示](https://demo.skymaster.io) | [文档](https://docs.skymaster.io) | [API文档](https://api.skymaster.io/docs)

</div>

---

## 📋 项目简介

SkyMaster是一个开源的企业级无人机管控平台，支持多品牌无人机的统一管理、实时监控、任务规划和集群控制。

> 📖 **仓库结构说明**：仓库当前存在 `backend/` (v1.x legacy) 和 `backend-v0.1/` (v2.x 主线) 两组目录。新开发请到 `-v0.1/` 目录，详见 [`docs/REPO_STRUCTURE.md`](docs/REPO_STRUCTURE.md)。
>
> 🎯 **v2.0 已交付**：见 [`docs/V2.0_DELIVERY_REPORT.md`](docs/V2.0_DELIVERY_REPORT.md) · **v2.1 已启动**：见 [`docs/V2.1_KICKOFF.md`](docs/V2.1_KICKOFF.md)

### 核心特性

✈️ **多平台兼容**
- 支持PX4飞控系统
- 支持ArduPilot飞控系统
- 支持大疆DJI无人机（通过DJI SDK）
- 支持其他MAVLink协议设备

📡 **实时监控**
- 3D地图显示（Cesium.js）
- 实时遥测数据显示
- 多机同时监控
- 视频流显示（RTSP/RTMP/WebRTC）
- 3D姿态仪表盘

🗺️ **任务规划**
- 可视化航点规划
- 自动航线生成
- 任务模板管理
- 批量任务上传

🤖 **集群管理**
- 多机协同控制
- 编队飞行（V形、圆形、网格等）
- 智能任务分配
- 碰撞避免

📊 **数据分析**
- 飞行日志回放
- 数据可视化图表
- 飞行报告生成
- AI辅助分析

🔒 **安全管理**
- 地理围栏（Geofencing）
- 失联自动返航
- 低电量保护
- 权限管理

---

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                        前端应用层                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ 3D地图    │  │ 仪表盘   │  │ 任务规划  │  │ 视频监控  │   │
│  │Cesium.js │  │ React    │  │ 编辑器    │  │ WebRTC   │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└─────────────────────────────────────────────────────────────┘
                           ↕ WebSocket/REST API
┌─────────────────────────────────────────────────────────────┐
│                        后端服务层                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │MAVLink   │  │ 设备管理  │  │ 任务规划  │  │ 集群控制  │   │
│  │ 连接器   │  │  服务    │  │  服务    │  │  服务    │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ 视频流   │  │ 数据分析  │  │ 安全管理  │  │ AI服务   │   │
│  │  服务    │  │  服务    │  │  服务    │  │         │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└─────────────────────────────────────────────────────────────┘
                           ↕
┌─────────────────────────────────────────────────────────────┐
│                        数据存储层                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │PostgreSQL│  │TimescaleDB│  │  Redis   │  │RabbitMQ  │   │
│  │ 业务数据 │  │ 时序数据  │  │  缓存    │  │ 消息队列 │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└─────────────────────────────────────────────────────────────┘
                           ↕
┌─────────────────────────────────────────────────────────────┐
│                        硬件设备层                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │   PX4    │  │ArduPilot │  │   DJI    │  │  其他    │   │
│  │  无人机  │  │  无人机  │  │  无人机  │  │MAVLink  │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 🚀 快速开始

### 前置要求

- Python 3.9+
- Node.js 16+
- Docker & Docker Compose
- PostgreSQL 13+
- Redis 6+

### 使用Docker部署（推荐）

```bash
# 1. 克隆项目
git clone https://github.com/your-org/skymaster-drone-platform.git
cd skymaster-drone-platform

# 2. 配置环境变量
cp .env.example .env
# 编辑.env文件，设置必要的配置

# 3. 启动服务
cd docker
docker-compose up -d

# 4. 访问应用
# 前端: http://localhost
# API文档: http://localhost:8000/docs
# Grafana监控: http://localhost:3000
```

### 手动部署

#### 后端部署

```bash
# 1. 安装依赖
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 2. 配置数据库
# 创建PostgreSQL数据库
createdb skymaster

# 3. 运行迁移
alembic upgrade head

# 4. 启动服务
uvicorn api.v1.main:app --host 0.0.0.0 --port 8000
```

#### 前端部署

```bash
# 1. 安装依赖
cd frontend
npm install

# 2. 配置环境变量
cp .env.example .env.local
# 编辑.env.local文件

# 3. 开发模式运行
npm run dev

# 4. 生产构建
npm run build
npm start
```

#### 视频墙开发环境（无 docker）

前端视频墙 `/dashboard/video-wall` 依赖 MediaMTX 流媒体服务与无人机推流。无真机时，
用合成流（ffmpeg lavfi）模拟无人机相机，一条命令起整条链路：

```bash
# 前置：后端 dev 栈已启动、FAKE-SIM-01/02 已 seed（scripts/seed_drones.py）
scripts/dev_video_stack.sh          # = start，幂等，已在跑的组件自动跳过
scripts/dev_video_stack.sh status   # 查看各组件状态
scripts/dev_video_stack.sh stop     # 停 watchdog + ffmpeg + mediamtx
```

链路与约定：

```
ffmpeg lavfi (testsrc2/smptebars)
  -> RTSP rtsp://127.0.0.1:8554/drone-{uuid}
  -> MediaMTX (HLS :8888, API :9997)
  -> 后端 /api/v1/streams 按 "drone-{uuid}" 路径自动绑定无人机
  -> 前端视频墙零配置自动上墙
```

- MediaMTX 二进制位于 `~/tools/mediamtx`，配置 `~/tools/mediamtx.yml`；
  已开启 `hlsAlwaysRemux: yes`（避免无观看者 60s 后 HLS muxer 销毁导致前端冷启动 404）
- 推流看门狗 `scripts/dev_video_push_watchdog.sh` 在 RTSP 会话断开后自动重推
- 踩坑备注见脚本头部注释（ffmpeg 8.x 无 `-stimeout`、bash 只读 `UID`、系统 python3 无 asyncpg）

---

## 📖 使用指南

### 1. 连接无人机

```python
# 通过API注册无人机
POST /api/devices
{
  "drone_id": "drone_001",
  "drone_type": "px4",
  "connection_string": "udp:127.0.0.1:14550",
  "name": "Alpha Drone"
}

# 连接无人机
POST /api/devices/drone_001/connect
```

### 2. 创建任务

```python
# 创建任务
POST /api/missions
{
  "mission_id": "mission_001",
  "name": "Survey Mission",
  "mission_type": "survey",
  "waypoints": [
    {
      "waypoint_id": "wp_001",
      "position": {"latitude": 39.9042, "longitude": 116.4074, "altitude": 50},
      "speed": 5.0
    }
  ]
}

# 上传任务到设备
POST /api/missions/mission_001/upload/drone_001
```

### 3. 集群控制

```python
# 创建集群
POST /api/swarms
{
  "swarm_id": "swarm_001",
  "name": "Alpha Team",
  "formation_type": "v_shape",
  "spacing": 10.0
}

# 编队成形
POST /api/swarms/swarm_001/form
{
  "latitude": 39.9042,
  "longitude": 116.4074,
  "altitude": 50
}
```

---

## 📚 文档

- [架构设计](docs/ARCHITECTURE.md)
- [API文档](docs/API.md)
- [部署指南](docs/DEPLOYMENT.md)
- [用户手册](docs/USER_GUIDE.md)
- [开发者指南](docs/DEVELOPER_GUIDE.md)

---

## 🛠️ 技术栈

### 后端
- **FastAPI** - 现代高性能Web框架
- **pymavlink** - MAVLink协议实现
- **PostgreSQL** - 关系型数据库
- **TimescaleDB** - 时序数据库
- **Redis** - 缓存和消息队列
- **Celery** - 异步任务队列
- **SQLAlchemy** - ORM框架

### 前端
- **React 18** - UI框架
- **TypeScript** - 类型安全
- **Ant Design** - UI组件库
- **Cesium.js** - 3D地球引擎
- **Three.js** - 3D渲染
- **ECharts** - 数据可视化
- **React Query** - 数据获取

### 通信
- **WebSocket** - 实时通信
- **RTSP** - 视频流
- **WebRTC** - 点对点视频

### 部署
- **Docker** - 容器化
- **Nginx** - 反向代理
- **Prometheus** - 监控
- **Grafana** - 可视化

---

## 🤝 贡献指南

我们欢迎所有形式的贡献！

### 如何贡献

1. Fork本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启Pull Request

### 开发规范

- 遵循PEP 8代码规范（Python）
- 遵循Airbnb代码规范（JavaScript/TypeScript）
- 编写单元测试
- 更新文档

---

## 📄 许可证

本项目采用MIT许可证 - 详见 [LICENSE](LICENSE) 文件

---

## 🙏 致谢

### 开源项目

- [ArduPilot](https://ardupilot.org/) - 开源飞控系统
- [PX4](https://px4.io/) - PX4自动驾驶仪
- [QGroundControl](http://qgroundcontrol.com/) - 地面站软件
- [dronekit-python](https://dronekit.io/) - Python无人机SDK
- [MAVSDK](https://mavsdk.mavlink.io/) - MAVLink库

---

## 📞 联系我们

- **官网**: https://skymaster.io
- **文档**: https://docs.skymaster.io
- **邮箱**: support@skymaster.io
- **Discord**: [加入社区](https://discord.gg/skymaster)
- **Twitter**: [@SkyMasterUAV](https://twitter.com/SkyMasterUAV)

---

## 🗺️ 路线图

### v1.0
- ✅ 多平台兼容（PX4/ArduPilot/DJI）
- ✅ 实时监控
- ✅ 任务规划
- ✅ 集群控制
- ✅ 3D地图显示

### v1.1 (当前版本)
- ✅ **AI路径规划** - A*智能路径搜索、地形跟随、能耗优化
- ✅ **自动避障** - 实时障碍检测、多机协同避障、紧急制动
- ✅ **完整测试** - 252个测试用例、84%覆盖率
- ✅ **详尽文档** - API文档、部署指南、用户手册、开发者指南

### v1.2 (计划中)
- ⏳ 视觉SLAM集成
- ⏳ 语音控制
- ⏳ AI异常检测

### v2.0 (未来)
- 📋 数字孪生
- 📋 边缘计算支持
- 📋 5G网络优化
- 📋 多域协同（空-地-水）

---

<div align="center">

**⭐ 如果这个项目对你有帮助，请给一个Star！⭐**

Made with ❤️ by SkyMaster Team

</div>
