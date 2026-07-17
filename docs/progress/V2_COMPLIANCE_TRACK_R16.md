# SkyMaster · v2.0 Compliance Track (R16) 会话/设备管理 · 密码热更改 · 会话追踪

> 2026-07-10 07:32 UTC · R15 之后继续
> 范围严格锁死：**非 AI / 非 3D-4D**

---

## ✅ 本轮四件套

### 1. ActiveSession 模型 + Alembic 20260710_0010
`app/models/active_session.py`：
- 字段：id / user_id FK CASCADE / **jti UNIQUE** / ip / country / user_agent / device_label / created_at / last_seen_at / revoked_at
- **jti UNIQUE** 保证一个 refresh token 一行记录
- 3 个索引：user_id / jti / created_at
- 软删设计：`revoked_at IS NULL` = 活跃会话

### 2. Session Tracker 服务
`app/services/session_tracker.py` — 三段式生命周期：
- **`record_session()`** — 登录成功时插入行；解码 refresh JWT 拿 jti/sub
- **`touch_or_rotate_session()`** — refresh 旋转时旧行 `revoked_at=now` + 新行插入
- **`revoke_by_jti()`** — logout 时按 jti 标记撤销
- 内置 UA 解析：iPhone/iPad/Android/Windows·Chrome/macOS·Safari 等 10+ 设备标签

### 3. 会话管理 API
`app/api/v1/auth_sessions.py`：
| 端点 | 说明 |
|---|---|
| `GET /auth/sessions` | 列出当前用户所有活跃会话，`is_current` 标记当前设备 |
| `DELETE /auth/sessions/{id}` | 撤销特定会话（同时加入 RevokedToken） |
| `POST /auth/sessions/revoke-others` | 一键登出其他所有设备（保留当前） |
| `POST /auth/change-password` | 修改密码 + 自动撤销 sibling 会话，返回 `revoked_sessions` 计数 |

**`change-password` 安全设计：**
- 需要当前密码（防会话劫持）
- 密码策略 R11 前置校验
- 新旧密码不能相同（bcrypt verify）
- 修改成功后自动撤销其他所有活跃会话，当前保留

### 4. 前端"设备与安全"页
`/dashboard/sessions`：
- **设备图标**：📱 iPhone/Android → MobileOutlined，💻 Mac/Win/Linux → LaptopOutlined
- **当前设备绿色 Tag** 突出
- **警告条**：其他设备 >0 → 提示"登出其他设备"操作
- **修改密码 Modal** — Warning Alert 提示会强制登出其他会话
- 客户端 12 位密码 + 二次确认
- 双向确认按钮 Popconfirm 防误操作
- 侧边栏新增"设备与安全"菜单（DesktopOutlined）

---

## 集成点

**auth.py 集成 session tracker：**
- `/auth/login` 成功 → `record_session()`
- `/auth/refresh` 旋转 → `touch_or_rotate_session()`（旧 revoked + 新 created）
- `/auth/password` (旧接口) 修改成功 → 撤销所有会话（保留 back-compat 行为）
- `/auth/change-password` (R16 新接口) → 撤销 sibling + 保留当前

---

## 测试统计

```
Backend total:  116 pass (+4 auth_sessions) / 8 skipped · 全绿
Frontend tsc:   0 error
```

**RevokedToken schema bug 修复**：R11 引入的 `revoked_tokens.exp NOT NULL` 约束未被新代码遵守，导致 IntegrityError；R16 全部撤销点已补 `exp=now`。

---

## 全套认证栈完整闭环

| Track | 里程碑 |
|---|---|
| R10 | JWT 短 access + refresh 旋转 |
| R11 | 密码策略 + Revocation + Logout |
| R12 | 2FA/TOTP + Lockout + 常量时间 bcrypt |
| R13 | Backup code + IP 限流 + OAuth2 |
| R14 | 登录审计 + 异地/异常检测 |
| R15 | 忘记/重置密码 + SMTP + 反枚举 |
| **R16** | **设备/会话管理 + 密码热更 + UA 指纹 + 一键登出** |

---

## 攻击矩阵累积

| 攻击/场景 | 拦截层 |
|---|---|
| Refresh token 被盗 | **R16 用户可在 /sessions 一键撤销** |
| 密码被盗登录多设备 | **R16 change-password 自动踢掉其他会话** |
| Session 劫持 | **R16 change-password 强制 verify current** |
| 长期离线设备残留 | **R16 用户可主动清理** |
| Rotation replay | **R16 old jti revoked_at=now** |

---

## 遗留 / 下一根桩

**仍在 v2.0 非 AI / 非 3D 范围：**

- [ ] SAML 2.0（企业用户）
- [ ] MaxMind GeoIP 数据库集成
- [ ] Redis 版 rate_limit（多实例）
- [ ] 批量操作审计中间件
- [ ] Email verification（注册确认）
- [ ] 通知子系统（邮件 + WebSocket 桥）
- [ ] API Key 管理（长期访问凭证）
- [ ] Docker 分发 → v1.0 GA 收官时再做 ✅

🐈 v2.0 R16 落地。
