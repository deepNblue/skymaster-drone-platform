# SkyMaster · v2.0 Compliance Track (R13) Backup Code 持久化 · IP Rate Limit · OAuth2 SSO (Google/GitHub)

> 2026-07-10 04:52 UTC · R12 之后继续
> 范围严格锁死：**非 AI / 非 3D-4D**

---

## ✅ 本轮三件套

### 1. Backup Code 服务端持久化 + 一次性消耗
`app/models/backup_code.py` + Alembic `20260710_0007`：
- **表**：`backup_codes(id, user_id FK cascade, code_hash, used_at, created_at)`
- **只存 bcrypt hash**，明文仅返回给用户一次（setup 时）
- `used_at` NULL 表示未消耗 → 一次性使用后打时间戳

`app/api/v1/auth_2fa.py`：
- `POST /2fa/setup` — 生成 10 个 backup code，bcrypt hash 后逐条 INSERT；清理旧 pending 码
- `POST /2fa/disable` — 关闭 2FA 同时 CASCADE 删除所有 backup code
- **新增** `POST /2fa/backup-codes/regenerate` — 需 TOTP 证明，重新生成 10 个（旧作废）

`/auth/login` 双通道验证：
1. **6 位数字** → 走 TOTP verify
2. **≥8 字符** → 遍历 unused backup codes 用 bcrypt checkpw 比对，命中即打 used_at
- 均失败 → `on_failure()` + 401

### 2. IP 速率限制
`app/services/rate_limit.py`：
- 内存滑动窗口（deque + async lock），Redis 版可后续接入
- **默认策略**：10 次 / 60 秒 / IP，`LOGIN_RATE_MAX` + `LOGIN_RATE_WINDOW_S` env 可调
- 支持 `X-Forwarded-For` 首个 IP（代理背后合规）
- 429 返 `Retry-After` header

集成点：
- `/auth/login` FIRST STEP 检查（bcrypt 前拦截）
- `/auth/refresh` 同样纳入预算（防 token grinding）

单元测试 4 条：阈值内通过 / 触发 429 + Retry-After / 多 IP 隔离 / XFF 优先

### 3. OAuth2 SSO — Google + GitHub
`app/api/v1/auth_sso.py`（httpx + python-jose，**无 Authlib 依赖**）：
- **`GET /auth/sso/providers`** — 列出已配置的 providers
- **`GET /auth/sso/{provider}/authorize`** — 302 重定向到第三方
  - `state` 参数是签名 JWT（5 分钟 TTL + nonce），防 CSRF
- **`GET /auth/sso/{provider}/callback`** — 换 token → 拉 userinfo → **upsert User** → 签发 access+refresh
  - GitHub 特例：email hidden 时二次调 `/user/emails` 抓 primary+verified
  - 新用户默认 `role="operator"` + 随机不可用密码（sso_sub 记录第三方 subject）
  - 已存在 email 自动补 sso_sub（首次 SSO 登录绑定）
- 全部走 env：`OAUTH_GOOGLE_CLIENT_ID/SECRET` / `OAUTH_GITHUB_CLIENT_ID/SECRET` / `OAUTH_REDIRECT_BASE`
- 未配置 provider → 端点自动 404

单元测试 7 条：无 provider / 单 provider 注册 / authorize 302 重定向 / state 签名/校验 / 坏 state 400

---

## 前端集成

### Login 页 (`app/login/page.tsx`)
- 挂载时拉 `/auth/sso/providers`，动态渲染 SSO 按钮
- **Google 按钮** (GoogleOutlined) + **GitHub 按钮** (GithubOutlined)
- 无 provider 配置 → 分隔线和按钮自动隐藏
- 2FA 输入框支持 **6 位数字 或 XXXXX-XXXXX 备份码格式**
- 客户端 validator 正则匹配双格式

---

## 测试统计

```
Backend total:  101 pass (+11 rate_limit/sso) / 8 skipped · 全绿
Frontend tsc:   0 error
```

---

## 认证矩阵完整闭环（R10 + R11 + R12 + R13）

| 攻击 / 场景 | 拦截层 |
|---|---|
| 密码暴破 | R12 lockout + **R13 IP 速率限制** |
| 密码字典 | R11 密码策略 |
| 密码泄露 | R12 TOTP 2FA + **R13 备份码持久化** |
| 用户丢失手机 | **R13 backup code 一次性使用** |
| Refresh replay | R11 jti blacklist + 旋转 |
| Access 泄露 | R10 短时效 + R11 撤销列表 |
| CSRF on OAuth redirect | **R13 signed state JWT + nonce** |
| 三方登录首次绑定 | **R13 sso_sub 自动 upsert** |
| Timing oracle | R12 常量时间 bcrypt |
| Token grinding | **R13 refresh 同享 IP 预算** |

---

## 累积能力

| Track | 里程碑 |
|---|---|
| v0.1 base | LL/MM/NN/OO/PP/QQ/RR/SS + 3D 模型 |
| v2.0 R1-R12 | 全套认证栈（密码/JWT/撤销/2FA/lockout） |
| **v2.0 R13** | **Backup code 持久化 + IP 速率限制 + OAuth2 Google/GitHub SSO** |

---

## 遗留 / 下一根桩

**仍在 v2.0 非 AI / 非 3D 范围：**

- [ ] SAML 2.0 支持（企业用户）
- [ ] 批量操作审计中间件
- [ ] 邮件/短信告警（异地登录、密码变更）
- [ ] Redis 版 rate_limit（多实例部署）
- [ ] OpenAPI security schemes 完善
- [ ] Docker 分发 → v1.0 GA 收官时再做 ✅

🐈 v2.0 R13 落地。
