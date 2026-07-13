# SkyMaster 项目接手报告 (Handoff Report)

> **目的**: 让接手人 / 新机器在 **30 分钟内** 跑通项目，1 天内理解整体架构，独立继续开发。
> **生成日期**: 2026-07-08
> **项目版本**: v1.1.0
> **代码规模**: 14,518 行（Backend 13,297 + Frontend 1,221）
> **最后活跃**: 2026-03-11（近 4 个月未动）

---

## 0. 一句话概览

**SkyMaster** 是一个基于 **FastAPI + React + PostgreSQL + Redis** 的企业级无人机集群管控平台，已完成 v1.1（含 AI 路径规划 + 自动避障），代码 + 文档 + Docker 部署 + CI/CD 全套齐备，处于"**开发完成、待实机测试**"状态。

---

## 1. 快速上手（30 分钟）

### 1.1 前置要求

| 组件 | 版本 |
|---|---|
| Python | 3.9+ |
| Node.js | 16+ |
| Docker + Docker Compose | 20+ |
| Git | 2+ |
| 磁盘 | 5 GB+（含镜像） |
| 内存 | 8 GB+（跑全部服务） |

### 1.2 从零启动（Docker 一键方案 · 推荐）

```bash
# 1. 解压项目
tar -xzf skymaster-drone-platform-YYYYMMDD.tar.gz
cd skymaster-drone-platform

# 2. 拉起全部服务（Postgres + TimescaleDB + Redis + RabbitMQ + Backend + Frontend）
cd docker
docker-compose up -d

# 3. 查看服务状态
docker-compose ps

# 4. 访问
# - 前端:   http://localhost:3000
# - 后端:   http://localhost:8000
# - OpenAPI: http://localhost:8000/docs
# - RabbitMQ管理台: http://localhost:15672 (skymaster / password)
```

### 1.3 本地开发模式（不用 Docker）

```bash
# ------ Backend ------
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# 需要本地起 Postgres/Redis，或者只跑 docker 的数据服务：
#   cd ../docker && docker-compose up -d postgres redis
uvicorn api.v1.main:app --reload --host 0.0.0.0 --port 8000

# ------ Frontend ------
cd ../frontend
npm install
npm run dev   # Next.js dev server → http://localhost:3000
```

### 1.4 用模拟器测试（无需真实无人机）

详见 `docs/SIMULATOR_QUICKSTART.md`（12KB，含 jMAVSim / Gazebo / AirSim 三套方案）。

最快路径：
```bash
# 装 PX4 SITL + jMAVSim（推荐入门）
docker run --rm -it -p 14550:14550/udp px4io/px4-dev-simulation-focal
# 然后在 SkyMaster 里连接 udpin:0.0.0.0:14550
```

---

## 2. 项目现状（诚实版本）

### 2.1 ✅ 已完成

| 模块 | 状态 | 备注 |
|---|---|---|
| **Backend FastAPI** | ✅ | 4 大 API 路由：devices / missions / telemetry / swarm + safety + planning |
| **MAVLink 连接层** | ✅ | 721 行；支持 PX4 / ArduPilot / DJI；有 mock 模式（pymavlink 缺失时自动降级） |
| **设备管理** | ✅ | 582 行；连接管理 + 心跳 + 状态机 |
| **任务管理** | ✅ | 705 行；航点 / 巡逻 / 编队 / 自定义脚本 |
| **集群控制** | ✅ | 797 行；编队 + 协同 + 广播 |
| **AI 路径规划** (v1.1) | ✅ | A* + 地形跟随 + 能量优化，共 1,589 行 |
| **自动避障** (v1.1) | ✅ | 障碍检测 + 碰撞预测 + 动态重规划，共 2,381 行 |
| **前端 Next.js** | ✅ | Cesium 3D 地图 + 仪表盘 + 设备列表（1,221 行 · **仅骨架**） |
| **数据库** | ✅ | PostgreSQL + TimescaleDB (时序数据) |
| **测试** | ✅ | 252 用例，覆盖率 84% |
| **Docker Compose** | ✅ | 6 个服务一键起 |
| **CI/CD** | ✅ | GitHub Actions（.github/workflows/ci.yml + deploy.yml） |
| **文档** | ✅ | 10 份文档，共 ~154 KB |

### 2.2 ⚠️ 未完成 / 已知缺陷

| 问题 | 优先级 | 建议动作 |
|---|---|---|
| **未做过实机飞行测试** | 🔴 高 | 按 `docs/FLIGHT_TEST_GUIDE.md` 分 5 阶段推进 |
| **前端只有 2 个页面**（Monitor.tsx + DroneMap.tsx） | 🟡 中 | 补充设备详情、任务规划、集群编队等页面 |
| **无移动端**（package.json 提到 React Native，但 mobile/ 目录为空） | 🟢 低 | v2.0 再做 |
| **无用户认证 / RBAC 完整实现** | 🟡 中 | JWT 骨架有，需接入前端 + 数据库权限 |
| **视频流模块未实现**（仅在 requirements 里预留） | 🟡 中 | 用 GStreamer / WebRTC 补齐 |
| **`docs/images/logo.png` 缺失** | 🟢 低 | README 里的图片是占位 |
| **`demo.skymaster.io` / `docs.skymaster.io` 是占位链接** | 🟢 低 | 部署后再改 |
| **PROJECT_STATUS.md 等 4 个新文档未提交** | 🟡 中 | **接手第一步：先提交** |
| **`.pytest_cache/` 已加进 .gitignore**（本次修） | ✅ | 已处理 |
| **`{backend` 错误目录**（模板变量未渲染） | ✅ | 已清理 |

### 2.3 Git 状态

```
分支: develop (跟踪 origin/develop)
提交:
  3331d06 docs: Update README and add CHANGELOG for v1.1
  6abff7e feat: SkyMaster v1.1 - AI路径规划与自动避障
  dd87a61 feat: Initial commit - SkyMaster drone platform v1.0

远程: origin/develop, origin/main
未提交:
  - PROJECT_STATUS.md
  - docs/FLIGHT_TEST_GUIDE.md
  - docs/HARDWARE_SHOPPING_LIST.md
  - docs/SIMULATOR_QUICKSTART.md
```

**接手第一件事**：
```bash
cd skymaster-drone-platform
git add PROJECT_STATUS.md docs/FLIGHT_TEST_GUIDE.md docs/HARDWARE_SHOPPING_LIST.md docs/SIMULATOR_QUICKSTART.md .gitignore
git commit -m "docs: add project status, flight test, hardware, simulator guides"
git push origin develop
```

---

## 3. 架构速览

### 3.1 整体分层

```
┌──────────────────────────────────────────────────────────┐
│  Frontend (Next.js 14 + React 18 + AntD + MUI)           │
│  • Cesium 3D 地图  • ECharts 图表  • WebSocket 实时推送   │
└──────────────────────────────────────────────────────────┘
                        ↕ HTTPS / WSS
┌──────────────────────────────────────────────────────────┐
│  Backend (FastAPI 0.104)                                  │
│  ┌────────────────────────────────────────────────────┐  │
│  │ API 层  api/v1/                                    │  │
│  │   main.py · planning.py · safety.py                │  │
│  ├────────────────────────────────────────────────────┤  │
│  │ 业务层  core/                                       │  │
│  │   devices/ · missions/ · swarm/                    │  │
│  │   planning/ (A*+terrain)  safety/ (avoidance)      │  │
│  ├────────────────────────────────────────────────────┤  │
│  │ 协议层  core/mavlink/                              │  │
│  │   PX4 · ArduPilot · DJI (统一 MAVLink)             │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
      ↕                    ↕                    ↕
 PostgreSQL          TimescaleDB              Redis + RabbitMQ
 (业务数据)          (遥测时序)               (缓存 + 任务队列)
      ↕
   Drones (PX4/ArduPilot/DJI) ← MAVLink 协议
```

### 3.2 关键模块行数

| 文件 | 行数 | 说明 |
|---|---|---|
| `core/safety/safety_manager.py` | 930 | 安全规则引擎主控 |
| `core/safety/collision_avoidance.py` | 805 | 碰撞预测 + 动态重规划 |
| `core/swarm/controller.py` | 797 | 集群编队控制 |
| `api/v1/safety.py` | 738 | 安全 API |
| `core/mavlink/connector.py` | 721 | MAVLink 协议连接器 |
| `core/missions/planner.py` | 705 | 任务规划 |
| `core/planning/path_planner.py` | 665 | 路径规划主控 |
| `core/safety/obstacle_detector.py` | 646 | 障碍检测 |
| `api/v1/main.py` | 638 | FastAPI 主入口 |
| `core/devices/manager.py` | 582 | 设备管理 |

### 3.3 API 端点速查

```
GET  /                              健康检查
GET  /docs                          OpenAPI Swagger
GET  /health                        健康状态

设备:
GET    /api/v1/devices              列表
POST   /api/v1/devices              新增连接
GET    /api/v1/devices/{id}         详情
DELETE /api/v1/devices/{id}         断开

任务:
POST   /api/v1/missions             创建任务
GET    /api/v1/missions             列表
POST   /api/v1/missions/{id}/start  启动
POST   /api/v1/missions/{id}/pause  暂停

集群:
POST   /api/v1/swarm/formation      编队
POST   /api/v1/swarm/coordinate     协同

路径规划 (v1.1):
POST   /api/planning/path           生成最优路径
POST   /api/planning/optimize       优化已有路径
GET    /api/planning/terrain        地形数据

安全 (v1.1):
POST   /api/safety/detect           障碍检测
POST   /api/safety/avoid            生成避障路径
GET    /api/safety/status           安全状态

WebSocket:
WS     /ws/telemetry/{device_id}    遥测流
WS     /ws/video/{device_id}        视频流
```

---

## 4. 关键文档索引

| 文档 | 大小 | 用途 |
|---|---|---|
| `README.md` | 项目介绍与快速开始 | 第一眼看这个 |
| `PROJECT_STATUS.md` | 详细进度报告 | 接手前必读 |
| `CHANGELOG.md` | 版本变更 | 了解演进历史 |
| `docs/ARCHITECTURE.md` | 16 KB · 架构文档 | **理解系统必读** |
| `docs/API.md` | 18 KB · 40+ 端点 | 前后端联调 |
| `docs/DEPLOYMENT.md` | 20 KB · 部署指南 | 生产上线 |
| `docs/USER_GUIDE.md` | 22 KB · 用户手册 | 功能演示 |
| `docs/DEVELOPER_GUIDE.md` | 26 KB · 开发指南 | **二次开发必读** |
| `docs/FLIGHT_TEST_GUIDE.md` | 20 KB · 实机测试 | 5 阶段测试流程 |
| `docs/HARDWARE_SHOPPING_LIST.md` | 12 KB · 硬件清单 | 采购指导 |
| `docs/SIMULATOR_QUICKSTART.md` | 12 KB · 模拟器 | jMAVSim/Gazebo/AirSim |
| `docs/V1.1_ROADMAP.md` | 3 KB · 路线图 | 下一步 |
| `docs/TEST_REPORT.md` | 4 KB · 测试报告 | 252 用例结果 |
| `CONTRIBUTING.md` | 贡献规范 | PR 流程 |

---

## 5. 环境变量清单（生产必配）

`docker/docker-compose.yml` 里默认值仅供开发：

```bash
# 数据库
DATABASE_URL=postgresql://skymaster:CHANGE_ME@postgres:5432/skymaster
TIMESCALE_URL=postgresql://skymaster:CHANGE_ME@timescaledb:5432/skymaster_telemetry

# 缓存/队列
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/1
RABBITMQ_URL=amqp://skymaster:CHANGE_ME@rabbitmq:5672/

# 认证
JWT_SECRET=CHANGE_ME_TO_STRONG_SECRET
JWT_ALGORITHM=HS256
JWT_EXPIRATION_HOURS=24

# 环境
ENVIRONMENT=production      # development | staging | production
LOG_LEVEL=INFO
DEBUG=false
```

完整清单见 `docs/DEPLOYMENT.md`（100+ 个）。

---

## 6. 下一步优先级（建议接手路线）

### 🎯 Week 1（跑通 + 熟悉）
1. **提交 4 个 untracked 文档** ← 5 分钟
2. Docker Compose 一键起，跑通 http://localhost:8000/docs
3. 跑测试：`cd backend && pytest --cov`（目标 84% 覆盖率复现）
4. 通读 `docs/ARCHITECTURE.md` + `docs/DEVELOPER_GUIDE.md`

### 🎯 Week 2（模拟器测试）
5. 按 `docs/SIMULATOR_QUICKSTART.md` 装 PX4 SITL
6. 前端连接 SITL，验证遥测 + 起飞 + 航点
7. 触发一次自动避障场景

### 🎯 Week 3+（真机 + 前端）
8. 按 `docs/HARDWARE_SHOPPING_LIST.md` 采购最小验证套件
9. 补齐前端页面（当前只有 2 个 tsx）
10. 加用户认证 + RBAC

### 🎯 中期
11. 视频流模块（GStreamer / WebRTC）
12. 移动端（React Native）
13. 生产环境部署 + Prometheus + Grafana 监控

---

## 7. 危险区 / 踩坑提示

1. **pymavlink 装不上** → connector.py 有 mock，代码能跑但没实际通信
2. **TimescaleDB 首次启动慢** → 需要 30-60s 初始化，先 `docker-compose logs -f timescaledb`
3. **Cesium 需要 Ion Token** → 前端要在 `.env.local` 设 `NEXT_PUBLIC_CESIUM_TOKEN`
4. **Docker 挂载路径**（compose 里 `../backend:/app`） → 换机器时注意相对路径
5. **无实机测试** → **绝对不要**直接把当前代码上真机跑，必先 SITL 全流程验证
6. **CI 依赖 GitHub Secrets** → 换仓库后需重新配 `DEPLOY_HOST` / `DEPLOY_KEY`
7. **`develop` 是当前分支**，`main` 是稳定分支，PR 流程见 CONTRIBUTING.md

---

## 8. 项目文件树（清理后）

```
skymaster-drone-platform/
├── .github/workflows/       # CI/CD
│   ├── ci.yml
│   └── deploy.yml
├── backend/                 # Python FastAPI 后端 (13,297 行)
│   ├── api/v1/
│   │   ├── main.py         # 主入口
│   │   ├── planning.py     # 路径规划 API
│   │   └── safety.py       # 安全 API
│   ├── core/
│   │   ├── devices/        # 设备管理
│   │   ├── missions/       # 任务规划
│   │   ├── mavlink/        # MAVLink 协议
│   │   ├── swarm/          # 集群控制
│   │   ├── planning/       # AI 路径规划 (A*)
│   │   └── safety/         # 避障 + 安全
│   ├── tests/              # 252 用例
│   ├── config.py
│   └── requirements.txt
├── frontend/               # Next.js 14 前端 (1,221 行 · 骨架)
│   ├── src/
│   │   ├── dashboard/Monitor.tsx
│   │   └── maps/DroneMap.tsx
│   └── package.json
├── docker/
│   └── docker-compose.yml  # 6 服务
├── docs/                   # 10 份文档 (~154 KB)
│   ├── ARCHITECTURE.md
│   ├── API.md
│   ├── DEPLOYMENT.md
│   ├── USER_GUIDE.md
│   ├── DEVELOPER_GUIDE.md
│   ├── FLIGHT_TEST_GUIDE.md
│   ├── HARDWARE_SHOPPING_LIST.md
│   ├── SIMULATOR_QUICKSTART.md
│   ├── V1.1_ROADMAP.md
│   └── TEST_REPORT.md
├── README.md
├── PROJECT_STATUS.md       # ⚠️ 未提交
├── CHANGELOG.md
├── CONTRIBUTING.md
├── LICENSE                 # MIT
└── .gitignore
```

---

## 9. 联系 / 支持

- **原开发者**: 通过 nanobot 助手（当前会话）
- **代码托管**: GitHub (URL 见 README)
- **License**: MIT — 可自由 fork / 商用

---

**祝换机器顺利。有任何问题，先看 `docs/DEVELOPER_GUIDE.md`，90% 的疑问都在里面。** 🚁
