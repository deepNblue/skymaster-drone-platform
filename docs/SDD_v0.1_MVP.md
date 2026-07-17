# SkyMaster v0.1 MVP · Software Design Document

- **版本**：v0.1-draft · 2026-07-09
- **对齐**：PRODUCT_SPEC v1.5 §10.1（v0.1 MVP · 3 个月）
- **目标**：单集群 docker-compose 部署 · PX4/ArduPilot 单机接入 · 基础任务规划 + 实时遥测 + 单路视频 + Web 控制台

---

## 1. 系统总体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      Web Console (Next.js)                      │
│    Dashboard · 任务规划 · 实时监控 · 设备管理 · 日志            │
└──────────────┬────────────────────────┬─────────────────────────┘
       HTTPS/WSS│                       │WebRTC (v0.5+, MVP 用 HLS)
┌──────────────▼───────────────────────────────────────────────┐
│                    API Gateway (FastAPI)                     │
│  /api/v1/*  REST  ·  /ws/*  WebSocket  ·  Auth (JWT/OIDC)    │
└──┬──────┬──────┬──────┬──────┬──────────────────────────────┘
   │      │      │      │      │
┌──▼──┐┌──▼──┐┌──▼──┐┌──▼──┐┌──▼────────┐
│Dev  ││Miss ││Tele ││Safe ││Stream/Media│
│Mgr  ││Plan ││metry││ty   ││(HLS Proxy) │
└──┬──┘└──┬──┘└──┬──┘└──┬──┘└──┬─────────┘
   │      │      │      │      │
┌──▼──────▼──────▼──────▼──────▼─────────┐
│    MAVLink Connector (pymavlink)       │
│   UDP:14550 / TCP · v2 protocol         │
└────────────────┬───────────────────────┘
                 │
┌────────────────▼─────────────────────────┐
│  PX4 / ArduPilot (SITL or Real Drone)    │
└──────────────────────────────────────────┘

存储/中间件：
  PostgreSQL 15 (元数据)  ·  Redis 7 (会话/缓存)
  MinIO (媒体资产)  ·  TimescaleDB (遥测时序)
```

**MVP 简化决策**：
- 不引入 K8s（v0.5+），单机 docker-compose
- 不引入 Kafka（v0.5+），遥测走 Redis Streams
- 不引入 WebRTC（v1.0+），视频走 HLS 中转（延迟 3-6s 可接受）
- 不做 UTM 围栏（v1.0+）

---

## 2. 技术栈决策矩阵

| 层 | 选型 | 替代方案 | 决策依据 |
|---|---|---|---|
| API 框架 | FastAPI 0.104 | Django/Flask | 异步原生 + OpenAPI 自动 + Pydantic |
| ORM | SQLAlchemy 2.0 async | Tortoise/SQLModel | 生态成熟 · async 稳定 |
| 迁移 | Alembic | — | SQLAlchemy 官方搭档 |
| 消息 | Redis Streams | Kafka/RabbitMQ | MVP 单机足够 · 零运维 |
| 时序 | TimescaleDB | InfluxDB | 复用 PostgreSQL 认知 |
| 对象存储 | MinIO | 阿里 OSS | 私有化 + S3 兼容 |
| MAVLink | pymavlink 2.4 | mavsdk-python | 稳定 · 全协议覆盖 |
| 视频中转 | mediamtx (rtsp→hls) | SRS | 轻量 · Go 单文件 |
| 前端 | Next.js 14 + AntD 5 | Vue/Nuxt | 已勘察实际代码 |
| 部署 | docker-compose | K8s | MVP 单机 |

---

## 3. 数据模型（ER 图）

```
┌────────────┐        ┌────────────┐        ┌─────────────┐
│Organization│─1───∞─▶│    User    │        │   Drone     │
│  id (uuid) │        │ id, org_id │◀────∞──│ id, org_id  │
│  name      │        │ role,email │  owns  │ sn, model   │
│  tenant_ty │        │ hashed_pw  │        │ protocol    │
└────────────┘        └──────┬─────┘        │ status      │
                             │              └──────┬──────┘
                             │                     │
                             │                     │1
                             │                     │
                       ┌─────▼──────┐         ┌────▼────────┐
                       │  Mission   │─1────∞──│ FlightLog   │
                       │ id,org_id  │         │ id,mission  │
                       │ waypoints  │         │ ts,lat,lng  │
                       │ status     │         │ alt,speed   │
                       │ drone_id   │         │ battery,rss │
                       └─────┬──────┘         └─────────────┘
                             │                (TimescaleDB
                             │                 hypertable)
                             │1
                             │∞
                       ┌─────▼──────┐         ┌─────────────┐
                       │MediaAsset  │         │  AuditLog   │
                       │id, mission │         │ id, actor   │
                       │ type,key   │         │ action,resource│
                       │ minio_url  │         │ ts, diff    │
                       └────────────┘         └─────────────┘
                                              (append-only)
```

### 3.1 表 DDL 摘要

```sql
CREATE TABLE organization (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(120) NOT NULL,
    tenant_type VARCHAR(30)  NOT NULL DEFAULT 'standard',
    created_at  TIMESTAMPTZ  DEFAULT now()
);

CREATE TABLE users (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id     UUID REFERENCES organization(id) ON DELETE CASCADE,
    email      VARCHAR(255) UNIQUE NOT NULL,
    hashed_pw  VARCHAR(255) NOT NULL,
    role       VARCHAR(30)  NOT NULL DEFAULT 'operator',
    sso_sub    VARCHAR(255),
    created_at TIMESTAMPTZ  DEFAULT now()
);

CREATE TABLE drones (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id     UUID REFERENCES organization(id),
    sn         VARCHAR(60) UNIQUE NOT NULL,
    model      VARCHAR(60),
    protocol   VARCHAR(30) NOT NULL,  -- 'mavlink' | 'dji' | 'custom'
    status     VARCHAR(20) DEFAULT 'offline',
    metadata   JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE missions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       UUID REFERENCES organization(id),
    drone_id     UUID REFERENCES drones(id),
    name         VARCHAR(120) NOT NULL,
    template     VARCHAR(40),           -- 'waypoint' | 'grid' | 'orbit'
    waypoints    JSONB NOT NULL,         -- [{lat,lng,alt,speed,action}]
    params       JSONB DEFAULT '{}',
    status       VARCHAR(20) DEFAULT 'draft', -- draft/dispatched/running/done/failed
    created_by   UUID REFERENCES users(id),
    created_at   TIMESTAMPTZ DEFAULT now(),
    dispatched_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

-- 遥测走 TimescaleDB hypertable
CREATE TABLE flight_logs (
    time        TIMESTAMPTZ NOT NULL,
    drone_id    UUID NOT NULL,
    mission_id  UUID,
    lat         DOUBLE PRECISION,
    lng         DOUBLE PRECISION,
    alt         REAL,
    speed       REAL,
    heading     REAL,
    roll REAL, pitch REAL, yaw REAL,
    battery_pct REAL,
    rssi        SMALLINT,
    gps_sats    SMALLINT,
    flight_mode VARCHAR(20)
);
SELECT create_hypertable('flight_logs', 'time', chunk_time_interval => INTERVAL '1 day');
CREATE INDEX ON flight_logs (drone_id, time DESC);

CREATE TABLE media_assets (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id UUID REFERENCES missions(id),
    drone_id   UUID REFERENCES drones(id),
    type       VARCHAR(20),           -- 'photo' | 'video' | 'thermal'
    minio_key  TEXT NOT NULL,
    size_bytes BIGINT,
    captured_at TIMESTAMPTZ,
    metadata   JSONB DEFAULT '{}'
);

CREATE TABLE audit_logs (
    id       BIGSERIAL PRIMARY KEY,
    ts       TIMESTAMPTZ DEFAULT now(),
    actor_id UUID,
    action   VARCHAR(60) NOT NULL,
    resource VARCHAR(120),
    diff     JSONB,
    ip       INET,
    ua       TEXT
);
```

---

## 4. 接口详细设计（REST）

### 4.1 认证 · `/api/v1/auth`

| 方法 | 路径 | 请求体 | 响应 |
|---|---|---|---|
| POST | `/login` | `{email, password}` | `{access_token, refresh_token, user}` |
| POST | `/refresh` | `{refresh_token}` | `{access_token}` |
| POST | `/logout` | — | `204` |
| GET  | `/me` | header: Bearer | `{id, email, role, org}` |

### 4.2 设备 · `/api/v1/drones`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET    | `/` | 分页 · filter: `?status=&protocol=&q=` |
| POST   | `/` | 注册无人机（幂等 by `sn`） |
| GET    | `/{id}` | 详情（含最近一次遥测） |
| PATCH  | `/{id}` | 更新元数据 |
| DELETE | `/{id}` | 软删除 |
| POST   | `/{id}/connect` | 触发 MAVLink 连接 |
| POST   | `/{id}/disconnect` | 主动断开 |
| GET    | `/{id}/telemetry?from=&to=` | 历史遥测 · 上限 10k 点 |

### 4.3 任务 · `/api/v1/missions`

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/` | 创建 draft |
| GET  | `/` | 列表 · filter: `?status=&drone_id=` |
| GET  | `/{id}` | 详情 |
| POST | `/{id}/validate` | 校验（碰撞/围栏/续航） |
| POST | `/{id}/dispatch` | 下发至无人机（幂等） |
| POST | `/{id}/pause` | 暂停 |
| POST | `/{id}/resume` | 继续 |
| POST | `/{id}/abort` | 中止（RTL） |
| GET  | `/{id}/logs` | 该任务全量 flight_logs |

### 4.4 视频 · `/api/v1/streams`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/{drone_id}/hls` | 返回 HLS m3u8 URL（mediamtx 转封装） |
| GET | `/{drone_id}/snapshot` | 当前帧截图 JPEG |

### 4.5 WebSocket · `/ws/*`

```
/ws/telemetry/{drone_id}   实时遥测流（1Hz 默认，可 config 到 10Hz）
/ws/alerts                 全局告警订阅
/ws/mission/{id}/status    任务状态推送
```

**消息格式**（统一）：
```json
{
  "type": "telemetry" | "alert" | "mission_status",
  "ts":   "2026-07-09T10:00:00Z",
  "data": { ... }
}
```

---

## 5. 关键时序图

### 5.1 任务下发全流程

```
Web        API        MissionSvc    Redis       MavlinkConn   Drone
 │POST dispatch│           │           │             │           │
 │─────────────▶           │           │             │           │
 │           │validate     │           │             │           │
 │           │─────────────▶           │             │           │
 │           │             │check WP   │             │           │
 │           │             │check geofence│          │           │
 │           │             │check battery│           │           │
 │           │◀────────────ok          │             │           │
 │           │publish cmd  │           │             │           │
 │           │─────────────┼──────────▶│             │           │
 │           │             │           │consume      │           │
 │           │             │           │─────────────▶           │
 │           │             │           │             │upload WP  │
 │           │             │           │             │──────────▶│
 │           │             │           │             │◀────ack───│
 │           │             │           │             │mission_start│
 │           │             │           │             │──────────▶│
 │           │             │           │             │◀──HB──────│
 │           │             │           │             │           │
 │           │◀───────────update status: dispatched  │           │
 │◀──200 OK──│                                                   │
 │                                                               │
 │(WS 订阅 /ws/mission/{id}/status)                              │
 │◀─────────push: running──────────────────────────────────────  │
```

### 5.2 遥测数据链路

```
Drone ──MAVLink UDP──▶ Connector (pymavlink)
                          │
                          │ parse
                          ▼
                     TelemetryService
                          │
                          ├──▶ Redis Streams: telemetry:{drone_id}
                          │        │
                          │        ▼
                          │    WS Broadcaster ──▶ /ws/telemetry/{drone_id}
                          │
                          └──▶ TimescaleDB (batch insert, 每 5s)
                                   │
                                   ▼
                              GET /telemetry?from=&to=
```

---

## 6. 部署拓扑（docker-compose）

```yaml
services:
  postgres:      # TimescaleDB 镜像
    image: timescale/timescaledb:2.13-pg15
    volumes: [pg_data:/var/lib/postgresql/data]
    ports: ["5432:5432"]

  redis:
    image: redis:7-alpine
    volumes: [redis_data:/data]

  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    ports: ["9000:9000", "9001:9001"]
    volumes: [minio_data:/data]

  mediamtx:      # 视频中转
    image: bluenviron/mediamtx:latest
    ports: ["8554:8554", "8888:8888"]  # RTSP / HLS

  api:
    build: ./backend
    depends_on: [postgres, redis, minio]
    environment:
      DATABASE_URL: postgresql+asyncpg://sm:sm@postgres:5432/skymaster
      REDIS_URL:    redis://redis:6379/0
      MINIO_ENDPOINT: minio:9000
    ports: ["8000:8000"]

  mavlink-connector:  # 独立进程池
    build: ./backend
    command: python -m core.mavlink.connector
    network_mode: host   # 允许 UDP 广播接收
    depends_on: [redis]

  web:
    build: ./frontend
    depends_on: [api]
    ports: ["3000:3000"]
    environment:
      NEXT_PUBLIC_API: http://api:8000

volumes:
  pg_data:
  redis_data:
  minio_data:
```

**部署验收**：
```bash
docker compose up -d
docker compose ps    # 全部 healthy
curl localhost:8000/api/v1/health  # {"status":"ok"}
open http://localhost:3000
```

---

## 7. 安全设计（MVP 层级）

- **JWT**：HS256 · 短时 access（15min） + 长时 refresh（7d） · Redis 存黑名单
- **CORS**：白名单 · 默认拒绝
- **RBAC**：三角色 · `admin` / `operator` / `viewer`
- **审计**：所有非 GET 请求写 `audit_logs`
- **传输**：TLS 1.3（Nginx 前置）
- **敏感字段**：`hashed_pw` bcrypt cost=12 · `sso_sub` 不入日志
- **速率限制**：`/auth/login` 5次/分钟/IP
- **未覆盖（延后）**：等保三级、国密、SBOM、密钥轮换（v1.0）

---

## 8. 性能指标 & 容量规划

| 指标 | MVP 目标 | 备注 |
|---|---|---|
| 并发无人机接入 | ≤ 5 台 | 单机 MAVLink Connector |
| 遥测频率 | 1-10 Hz | 可配置 |
| API P95 延迟 | < 200ms | 简单查询 |
| 遥测端到端延迟 | < 500ms | Drone → WS |
| 视频延迟（HLS） | 3-6s | MVP 可接受 |
| 单机资源 | 4C8G / 100GB SSD | 5 机场景 |
| 数据保留 | flight_logs 90d · audit 1y | 后续加压缩 |

---

## 9. Sprint 拆解（3 个月 · 12 周）

| Week | 任务 | 交付 |
|---|---|---|
| W1 | 后端项目结构搭建 · docker-compose 骨架 · DB 迁移 | `docker compose up` 起来 |
| W2 | 认证 + 组织/用户 CRUD | `/api/v1/auth` + `/users` |
| W3 | 设备 CRUD + MAVLink Connector 单机连通 | 能收到 PX4 SITL 心跳 |
| W4 | 遥测入库 + WS 广播 | `/ws/telemetry/{id}` 可订阅 |
| W5 | 任务模型 + 航点校验 | `/api/v1/missions` CRUD |
| W6 | 任务下发（MAVLink WP upload） | SITL 能收到航点并起飞 |
| W7 | 视频中转 (mediamtx) + HLS 前端接入 | 前端能播放单路 |
| W8 | 前端主题 Token 落地（复用 I 交付） | AntD 军工风生效 |
| W9 | 4 大页面：登录 / Dashboard / 设备 / 任务 | 可用 |
| W10 | 4 大页面：监控 / 视频墙 / 日志 / 设置 | 可用 |
| W11 | 联调 · 压测 · Bug 修复 | 5 机并发通过 |
| W12 | 文档 · 部署手册 · Demo 视频 · v0.1 发布 | GitHub Tag v0.1.0 |

---

## 10. 遗留风险与开放问题

- ⚠️ MAVLink UDP `network_mode: host` 在 macOS Docker Desktop 上不生效 → 需 mac 用户额外配置
- ⚠️ mediamtx 中转 RTSP 需要机载图传设备暴露 RTSP · **DJI 无 RTSP**，DJI 视频延迟 v0.5+ 再处理
- ⚠️ 遥测 10Hz 时 Redis Streams 单机极限约 5-8 机，扩容需转 Kafka（v0.5+）
- ⚠️ 前端 Cesium 初次加载 3-5s，MVP 内可接受，v0.5 做 LOD 优化
- ⚠️ 未做多租户物理隔离（仅 row-level `org_id`）· 企业客户敏感数据需 v1.0 引入 schema-level 隔离

---

**文档负责人**：架构组
**版本**：v0.1-draft · 2026-07-09
**下一步**：架构评审 → Sprint 0 启动 → 每周 Demo 🐈
