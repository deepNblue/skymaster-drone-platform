# Sprint 0 · Backend v0.1 单 Pane 验证任务

**Agent 角色**：Backend Foundation Engineer
**工作目录**：`/home/duoduo/projects/skymaster-drone-platform/backend-v0.1/`
**核心 SDD**：`/home/duoduo/projects/skymaster-drone-platform/docs/SDD_v0.1_MVP.md`
**时限**：本次会话完成 · 目标 45-90 分钟内产出可跑通的 backend 骨架

---

## 🎯 交付目标

一句话：**从零搭出 SkyMaster v0.1 Backend 骨架，`docker compose up -d` 起来，`curl localhost:8000/api/v1/health` 通**。

---

## ✅ 具体交付清单（按顺序）

### 阶段 1 · 项目结构（10 分钟）

创建以下目录树：
```
backend-v0.1/
├── pyproject.toml           # Python 3.11+, poetry 或 pdm
├── README.md                # 快速起步说明
├── docker-compose.yml       # 全栈拓扑（见 SDD §6）
├── Dockerfile               # 后端镜像
├── .env.example             # 环境变量模板
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
│       └── 20260709_0001_initial.py   # 10 张表初始迁移
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI 入口 + healthcheck
│   ├── config.py            # Pydantic Settings（读 .env）
│   ├── db.py                # SQLAlchemy async engine
│   ├── deps.py              # 依赖注入（get_db / get_current_user）
│   ├── models/              # ORM 模型
│   │   ├── __init__.py
│   │   ├── organization.py
│   │   ├── user.py
│   │   ├── drone.py
│   │   ├── mission.py
│   │   ├── flight_log.py    # TimescaleDB hypertable
│   │   ├── media_asset.py
│   │   └── audit_log.py
│   ├── schemas/             # Pydantic 模型
│   │   ├── auth.py
│   │   ├── drone.py
│   │   └── mission.py
│   ├── api/
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── health.py
│   │       ├── auth.py
│   │       ├── drones.py
│   │       ├── missions.py
│   │       ├── streams.py
│   │       └── websocket.py
│   └── services/
│       ├── auth.py          # JWT + bcrypt
│       ├── mavlink.py       # 占位
│       └── telemetry.py     # 占位
└── tests/
    ├── __init__.py
    ├── conftest.py
    └── test_health.py
```

### 阶段 2 · docker-compose.yml（15 分钟）

对齐 SDD §6，包含：
- `postgres` (TimescaleDB 2.13-pg15)
- `redis` (7-alpine)
- `minio` (含 console)
- `mediamtx` (最新)
- `api` (build ./ )
- `mavlink-connector` (build ./ · command 独立进程)

**要求**：
- 所有服务 healthcheck 齐全
- volumes 持久化
- port 只暴露必需（api:8000, minio:9001, mediamtx:8888）
- `.env.example` 覆盖所有变量

### 阶段 3 · Alembic 初始迁移（20 分钟）

**10 张表**（SDD §3.1 完整 DDL）：
1. `organization`
2. `users`
3. `drones`
4. `missions`
5. `flight_logs`（**TimescaleDB hypertable**，`SELECT create_hypertable(...)` 用 `op.execute()`）
6. `media_assets`
7. `audit_logs`
8. `approval_requests`（Track A 占位，允许 nullable）
9. `ai_models`（Track B 占位）
10. `copilot_traces`（Track C 占位，简化版）

**要求**：
- 每张表 UUID 主键（`gen_random_uuid()`，需 `CREATE EXTENSION pgcrypto`）
- 时间字段用 `TIMESTAMPTZ DEFAULT now()`
- JSONB 字段有默认值 `'{}'`
- 关键索引齐全

### 阶段 4 · FastAPI 基础接口（20 分钟）

**必须实现**：
- `GET /api/v1/health` → 返回 `{"status":"ok","db":"ok","redis":"ok"}`（检查依赖）
- `POST /api/v1/auth/login` → JWT 生成
- `GET /api/v1/auth/me` → JWT 验证 + 返回用户信息
- `GET /api/v1/drones` → 分页返回（可先 mock 空列表）
- `POST /api/v1/drones` → 注册无人机
- `GET /api/v1/missions` → 列表
- `POST /api/v1/missions` → 创建 draft 任务

**可暂时不实现**（写 501 占位）：
- MAVLink 连接
- WebSocket 遥测
- 视频流

### 阶段 5 · 冒烟测试（15 分钟）

**必须能跑通**：
```bash
cd backend-v0.1
cp .env.example .env
docker compose up -d
# 等 20s 起来
curl -s localhost:8000/api/v1/health   # {"status":"ok",...}
pytest -x -q                           # 至少 test_health 通过
```

---

## 🛡️ 硬约束

1. **Python 版本**：3.11+（用 `sys.version_info >= (3,11)`）
2. **依赖版本**：
   - fastapi ≥ 0.104
   - sqlalchemy ≥ 2.0（async）
   - alembic ≥ 1.13
   - pydantic ≥ 2.5
   - asyncpg ≥ 0.29
   - redis ≥ 5.0
   - python-jose[cryptography] ≥ 3.3
   - passlib[bcrypt] ≥ 1.7
   - pytest-asyncio ≥ 0.23
3. **代码规范**：
   - 类型注解 100% 覆盖公共 API
   - 所有 endpoint 用 async def
   - 敏感信息（DB URL、JWT secret）必须从 env 读
4. **不要做**：
   - ❌ 不实现 MAVLink 真实连接（占位即可）
   - ❌ 不引入 WebRTC / Kafka / K8s
   - ❌ 不写前端代码
   - ❌ 不启动服务，等验证阶段一起来
5. **每完成一阶段**：在 `PROGRESS.md` 追加一行 `✅ 阶段 X 完成 - <时间> - <关键产出>`

---

## 📋 参考文档

- `/home/duoduo/projects/skymaster-drone-platform/docs/SDD_v0.1_MVP.md`（主要）
- `/home/duoduo/projects/skymaster-drone-platform/docs/PRODUCT_SPEC.md` §7 数据模型
- 现有代码可参考：`/home/duoduo/projects/skymaster-drone-platform/backend/`（v1.1 遗留，供了解风格）

**注意**：不要复用现有 backend 的代码，全新写。现有代码是 v1.1 单机版，与 v0.1 SDD 的多服务架构完全不同。

---

## 🏁 结束条件

在 `PROGRESS.md` 写入：
```
🎉 Sprint 0 · Backend v0.1 骨架完成
- docker compose up 通过：Y/N
- /api/v1/health 通过：Y/N
- pytest 通过：Y/N
- 遗留 TODO：<列表>
- 下一步建议：<列表>
```

然后停止。不要主动推进到 Sprint 1。

🐈
