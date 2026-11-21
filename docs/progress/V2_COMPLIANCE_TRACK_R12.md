# SkyMaster · v2.0 Compliance Track (R12) 2FA/TOTP · Brute-force Lockout · Revoked-token Cleanup

> 2026-07-10 04:39 UTC · R11 之后继续，Docker 分发暂缓
> 范围严格锁死：**非 AI / 非 3D-4D**

---

## ✅ 本轮四件套

### 1. User 模型扩展 + Alembic 20260710_0006
`app/models/user.py`：
- `failed_login_count INTEGER DEFAULT 0` — 连续失败次数
- `locked_until TIMESTAMP` — 锁定到期时间（NULL = 未锁定）
- `totp_secret VARCHAR(64)` — base32 TOTP 密钥（待验证前也存，enabled=false）
- `totp_enabled BOOLEAN DEFAULT false` — 是否已完成 2FA setup

### 2. Brute-force Lockout Policy
`app/services/lockout.py`：
- `MAX_FAILED=5` / `LOCK_MINUTES=15`（模块常量便于测试 monkeypatch）
- `is_locked(user)` / `on_success(user)` / `on_failure(user)` 三 API
- 集成到 `/auth/login`：
  1. **常量时间保护**：`user is None` 时也跑一次 bcrypt 防用户存在性 timing oracle
  2. `is_locked()` 早于 verify_password 检查 → 423 Locked
  3. 密码错跑 `on_failure()` + 剩余次数提示（`≤2` 时警告）
  4. 密码对跑 `on_success()` 清零计数器
- **单元测试** 7 条覆盖：无锁/过期锁/未来锁/重置/递增/阈值触发/过期清算

### 3. TOTP 2FA 完整闭环
`app/services/totp.py`（pyotp==2.10.0 已安装）：
- `generate_secret()` / `provisioning_uri(secret, email)` / `verify_totp(secret, code, window=1)` / `generate_backup_codes(n=10)`
- valid_window=1 容忍前后 30s 时钟漂移
- 备份码 5-5 分组格式（易读写）
- **单元测试** 4 条：secret 是 base32 / URI 结构 / 正确+错误码 / 备份码唯一

`app/api/v1/auth_2fa.py`：4 个 endpoint
- `GET /auth/2fa/status` — 当前状态
- `POST /auth/2fa/setup` — 生成 secret + QR 码 URI + 备份码，`totp_enabled` 保持 false 待验证
- `POST /auth/2fa/verify` — 提交动态码翻转 `totp_enabled=true` 完成 setup
- `POST /auth/2fa/disable` — 关闭 2FA 需再次验证（防 stolen access token 静默关 MFA）

`/auth/login` 加入 2FA 分支：
- 密码对之后检查 `totp_enabled`
- 无 code 返 **428 Precondition Required**（客户端据此弹 TOTP 输入框）
- code 错也算 lockout 失败一次（防暴破 TOTP）

### 4. RevokedToken Cleanup 后台任务
`app/services/revoked_token_cleanup.py` + `app/main.py` lifespan：
- `cleanup_expired_revocations()` 单次调用 `DELETE FROM revoked_tokens WHERE exp < now()`
- 后台 asyncio 任务 `_revoke_cleanup_loop()` 每 6 小时执行一次（`REVOKED_TOKEN_CLEANUP_HOURS` 可配）
- 通过 `ENABLE_REVOKED_TOKEN_CLEANUP=true` 开关（默认开启）
- lifespan finally 优雅取消，防泄漏

---

## 前端 2FA UI

### 登录页 (`/login/page.tsx`)
- 检测 **428 状态码** 自动切换到 "输入动态码" 模式
- Alert 提示 "请输入身份验证器 App 上显示的 6 位动态码"
- 支持 "返回重新输入密码" 回退

### 个人资料页 (`/dashboard/profile/page.tsx`)
- 新增 "双因素认证" Card 区块 + 已启用/未启用 Tag
- **Setup 流程 Modal**：
  - 顶部 Steps 3 步引导（扫码 / 验证 / 备份）
  - `<QRCode>` 组件渲染 provisioning URI
  - 手动密钥显示（不方便扫码的场景）
  - 6 位动态码输入
  - 备份码列表 monospace 展示 + 警告说明
- **Disable 流程 Modal**：再次要求输入 6 位动态码验证身份

### `lib/api.ts`
- `login()` 添加可选 `totpCode` 参数
- 新增 `get2FAStatus()` / `setup2FA()` / `verify2FA()` / `disable2FA()`

---

## 测试统计

```
Backend total:  90 pass (+11 lockout/totp) / 8 skipped · 全绿
Frontend tsc:   0 error
```

---

## 认证矩阵（R10 + R11 + R12）

| 攻击场景 | 拦截层 |
|---|---|
| 密码暴破 | R12 lockout（5 次锁 15 分） |
| 密码字典 | R11 密码策略（≥8 位 3 类字符+黑名单） |
| 密码泄露单点失守 | R12 TOTP 2FA |
| Refresh token 泄露 replay | R11 jti blacklist + 单次使用旋转 |
| Access token 泄露 | R10 短时效 60min + R11 撤销列表 |
| 服务端 session 篡改 | R11 signed JWT + RBAC 每请求校验 |
| Timing oracle | R12 常量时间 bcrypt 空跑 |

---

## 累积能力

| Track | 里程碑 |
|---|---|
| v0.1 base | LL/MM/NN/OO/PP/QQ/RR/SS + 3D 模型 |
| v2.0 R1-R11 | 合规/RBAC/JWT/审批/账户/密码策略/撤销列表 |
| **v2.0 R12** | **2FA/TOTP + Brute-force lockout + 常量时间登录 + Cleanup 后台任务** |

---

## 遗留 / 下一根桩

**仍在 v2.0 非 AI / 非 3D 范围：**

- [ ] Backup code 服务端持久化 + 一次性消耗（当前仅生成不存）
- [ ] SSO / OAuth2 (Google/GitHub/OIDC)
- [ ] SAML for enterprise
- [ ] 批量操作写审计中间件
- [ ] IP-based rate limit（fastapi-limiter）
- [ ] Docker 分发 → v1.0 GA 收官时再做 ✅

🐈 v2.0 R12 落地。
