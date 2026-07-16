# SkyMaster v0.1 · Sprint 0-3 + 实跑联调交付

## 累计进度
| Sprint | 内容 | 耗时 | Turns |
|---|---|---:|---:|
| 0 | 后端骨架 (脚手架/Docker/Alembic/FastAPI/Pytest) | 22 min | 97 |
| 1 | MAVLink 真实接入 | 11 min | 76 |
| 2-Y | 视频流 mediamtx | 4 min | 26 |
| 2-Z | 前端 Next.js 骨架 + 9 页 + Copilot 抽屉 | 8 min | 45 |
| 3-EE | Copilot v0.1 真实 LLM 后端 | 8 min | 40 |
| 3-CC | Cesium 3D 地图 | 6 min | 20 |
| 3-DD | Copilot 前端联调 | 5 min | 15 |
| 联调 | 装依赖 + 修 review bug + 冒烟 | 20 min | 主代理 |
| **合计** | | **~85 min** | **~320+** |

## 代码规模
- 后端: 61 Python 文件 · 5780 行
- 前端: 24 TSX/TS/CSS 文件 · 3300+ 行
- 总计: **9080+ 行 · 85 文件**

## 实跑验证结果 ✅

### 后端 pytest
```
36 passed, 1 skipped (integration)  in 1.42s
```

### 后端 uvicorn 启动
```
✅ backend ready · 21 OpenAPI 路由已注册
GET /api/v1/health           HTTP 200
POST /api/v1/auth/login      HTTP 422 (校验通过)
GET /api/v1/drones           HTTP 401 (auth 生效)
POST /api/v1/copilot/sessions HTTP 401
GET /api/v1/streams          HTTP 401
```

### 前端 Next.js 构建
```
✅ 12 pages 构建成功
Route (app)                              Size     First Load JS
○ /                                       400 B    87.9 kB
○ /login                                4.89 kB    272 kB
○ /dashboard                            6.88 kB    220 kB
○ /dashboard/drones                     14.2 kB    374 kB
○ /dashboard/missions                   2.11 kB    346 kB
○ /dashboard/streams                    6.19 kB    267 kB
○ /dashboard/live (Cesium 3D)           6.41 kB    222 kB
○ /dashboard/copilot                    7.17 kB    261 kB
○ /dashboard/approvals                  3.32 kB    336 kB
ƒ /dashboard/missions/[id]              6.15 kB    371 kB
ƒ /dashboard/streams/[drone_id]         10.9 kB    272 kB
```

### 前端 dev server 冒烟
```
9/9 页面 HTTP 200
```

## 修复清单（联调环节）
1. ✅ 依赖补装 (email-validator, fakeredis, aiosqlite, pytest-mock)
2. ✅ streams.py DELETE 204 缺 response_class=Response 修复
3. ✅ layout.tsx 拆分为 client `ThemeProvider`（server component 不能引 antd）
4. ✅ CesiumMap Viewer.onReady 迁移到 useEffect 首次挂载
5. ✅ next.config.js 添加 Cesium 静态资源拷贝 + webpack fallback
6. ✅ cesium@1.119 + resium@1.19-beta + @zip.js/zip.js@2.7.60 版本对齐
7. ✅ mission [id]/page.tsx waypoint 可选字段类型收窄

## 依赖状态
- 后端 venv: `/home/duoduo/projects/skymaster-drone-platform/backend-v0.1/.venv` (Python 3.11.15)
- 前端 node_modules: 519 packages 已装
- Docker: 未装（WSL 环境）
- pytest: 36 pass · 1 skip
- npm run build: ✅ 通过
- 前后端 dev 联调: ✅ 通过

## 遗留 TODO
- [ ] 用 Docker 起 postgres/redis/minio 做真集成测试
- [ ] MAVLink 与 PX4 SITL 联调
- [ ] LLM 火山引擎 API 真实调用（需 API key）
- [ ] Cesium 首屏 3D 渲染人工目视验证（需浏览器）

## 立即可跑
```bash
# 后端
cd backend-v0.1
.venv/bin/python -m pytest tests/ -q                     # 单测
.venv/bin/python -m uvicorn app.main:app --port 8000     # 启动

# 前端
cd frontend-v0.1
npm run dev              # dev server @ :3000
npm run build            # 生产构建
```

🐈
