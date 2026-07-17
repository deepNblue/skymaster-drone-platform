# ⚠️ Legacy 目录说明 · v1.x

**当前目录 `backend/` 是 SkyMaster v1.x (2026-06 之前) 的后端代码。**

**新功能请到 `../backend-v0.1/` 添加。**

详见：[`../docs/REPO_STRUCTURE.md`](../docs/REPO_STRUCTURE.md)

---

## 本目录仍在维护什么

- v1.0 基础 CRUD + MAVLink 桥接
- v1.1 AI 路径规划（A*/RRT*/RRT-Connect）
- v1.1 自动避障、地理围栏、返航
- **v2.0 阶段新增**：100 机压测框架（`tests/load/`），因为压测对象是本目录的 `WebSocketManager`

## 关系图

```
skymaster-drone-platform/
├── backend/          ← 你在这里 (v1.x legacy, ~14K 行)
│   ├── api/v1/       ← FastAPI 主入口 + planning + safety
│   ├── core/         ← MAVLink 桥接、任务规划
│   └── tests/load/   ← 100 机压测（挂在这里因为压测 WebSocketManager）
│
└── backend-v0.1/     ← v2.x 主线 (~52K 行, 128 次 v2.0 commit)
    ├── app/          ← v2.0 六大模块：报备/3DGS/Vision/Copilot/Community/Marketplace
    ├── alembic/      ← 数据库迁移
    └── tests/        ← v2.0 测试 + UAT 端到端演练
```

## 想快速判断该去哪个目录？

| 需求 | 目录 |
|------|------|
| 新增 v2.0 六大模块相关代码 | `../backend-v0.1/` |
| 修 AI 路径规划 / MAVLink 桥接 | 本目录 |
| 新增 100 机压测场景 | 本目录 `tests/load/` |
| 修 v2.x 业务 bug | `../backend-v0.1/` |

🐈
