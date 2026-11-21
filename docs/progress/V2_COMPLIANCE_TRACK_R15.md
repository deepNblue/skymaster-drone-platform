# SkyMaster · v2.0 Compliance Track (R15) 密码重置流程 · SMTP Mailer · 反枚举保护

> 2026-07-10 06:55 UTC · R14 之后继续
> 范围严格锁死：**非 AI / 非 3D-4D**

---

## ✅ 本轮四件套

### 1. SMTP Mailer 服务
`app/services/mailer.py`：
- **`send_email(to, subject, body, html)`** — 单点发件 API
- **异步 executor 包装** 避免阻塞 event loop
- 全套 env 配置：`SMTP_HOST/PORT/USER/PASSWORD/TLS/FROM/FROM_NAME`
- **Dev fallback**：`SMTP_HOST` 未配置 → 打印到 stdout（不阻断测试）
- Best-effort：失败返 False + logger.warning 不 raise，认证流不受影响

### 2. PasswordResetToken 模型 + Alembic 20260710_0009
`app/models/password_reset_token.py`：
- 字段：id / user_id FK cascade / **token_hash** (bcrypt) / used_at / expires_at / created_at
- 2 个索引：user_id + token_hash 前缀
- **原始 token 从不落地**，仅 bcrypt hash 存 DB

### 3. `/auth/forgot-password` + `/auth/reset-password` 端点
`app/api/v1/auth_reset.py`：

**forgot-password 反枚举设计：**
- 无论 email 是否注册均返 200 `{ok:True}` — 消除账户枚举 oracle
- 生成 32-byte urlsafe token → bcrypt hash 入库
- 30 分钟 TTL，发中英双语邮件（HTML+纯文本）
- 复用 R13 IP 速率限制预算

**reset-password 安全链路：**
- 密码强度校验前置（R11 policy）
- 扫描 unused 未过期 token → bcrypt 比对（`used_at.is_(None)` + `expires_at > now`）
- 命中即改 hashed_pw + 标记 `used_at` + **CASCADE 删除同用户所有其他 unused token**
- 成功清 lockout 状态（R12 集成）
- 附 `cleanup_expired_reset_tokens()` 定时清理 helper

### 4. 前端 3 页 UI
- **`/forgot-password`** — 邮箱输入 + 提交后统一"已发送"提示（哪怕 API 报错也 fake success 防枚举）
- **`/reset-password?token=xxx`** — 新密码 + 确认 + 客户端 12 位校验；空 token → 引导重新申请
- **`/login`** — 右下角"忘记密码？"链接跳转

---

## 测试统计

```
Backend total:  112 pass (+4 auth_reset) / 8 skipped · 全绿
Frontend tsc:   0 error
```

**新增 conftest 修补**：SQLite 兼容层清理 Postgres 专属 `server_default` (`gen_random_uuid()` / `::jsonb` / `now()`)，保留 boolean/int 默认值不动 — 让集成测试能在内存 SQLite 上完整跑通 User+PasswordResetToken 表。

---

## 全套认证栈完整闭环

| Track | 里程碑 |
|---|---|
| R10 | JWT 短 access + refresh 旋转 |
| R11 | 密码策略 + Revocation + Logout |
| R12 | 2FA/TOTP + Lockout + 常量时间 bcrypt |
| R13 | Backup code + IP 限流 + OAuth2 Google/GitHub |
| R14 | 登录审计 + 异地/异常检测 + 双端 UI |
| **R15** | **忘记/重置密码 + SMTP + 反枚举 + 单次 token** |

---

## 攻击矩阵累积

| 攻击/场景 | 拦截层 |
|---|---|
| 账号枚举 | **R15 forgot-password 恒返 200** |
| 密码重置 replay | **R15 used_at 单次消耗** |
| 重置 token 泄露 | **R15 bcrypt hash + 30min TTL** |
| 重置期间 refresh 泄露 | **R15 同用户所有 token 一次性作废** |
| 弱密码回滚 | **R15 reset 继承 R11 策略校验** |
| SMTP 中断 | **R15 dev fallback + best-effort 不阻塞** |

---

## 遗留 / 下一根桩

**仍在 v2.0 非 AI / 非 3D 范围：**

- [ ] SAML 2.0（企业用户）
- [ ] MaxMind GeoIP 数据库集成
- [ ] Redis 版 rate_limit（多实例）
- [ ] 批量操作审计中间件
- [ ] Docker 分发 → v1.0 GA 收官时再做 ✅
- [ ] 通知子系统（邮件 + WebSocket 桥）
- [ ] Email verification (register-time confirm)

🐈 v2.0 R15 落地。
