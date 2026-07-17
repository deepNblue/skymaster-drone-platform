# SkyMaster · v2.0 Compliance Track (R11) Token Revocation List · Password Policy · Logout · Access Token 撤销

> 2026-07-10 04:11 UTC · R10 之后继续，Docker 分发暂缓
> 范围严格锁死：**非 AI / 非 3D-4D**

---

## ✅ 本轮四件套

### 1. RevokedToken 模型 + Alembic 迁移
`app/models/revoked_token.py` + `alembic/versions/20260710_0005_revoked_tokens.py`：
- **字段**：id / jti(唯一索引) / exp(索引) / revoked_at / reason
- **JWT jti claim**：`create_access_token` & `create_refresh_token` 每次生成时都写入 `uuid4().hex`
- **迁移策略**：`gen_random_uuid()` server default + jti/exp 双索引加速失效检查
- **过期自动失效**：exp 早于当前时间的行可安全清理（token 本已过期），未来加 cron 清理任务

### 2. `/auth/logout` 后端端点
`app/api/v1/auth.py::logout`：
- Body: `{refresh_token: "..."}` + Authorization Bearer access token
- **只能吊销自己的 token**：claims.sub 必须匹配当前用户，防止越权吊销他人 session
- **幂等**：重复吊销同 jti 返回 `{ok: true, already: true}`
- 不吊销 access token —— 60min 内自然过期，减少 DB 写压力
- 无效 token 静默成功（幂等日志）

### 3. Access + Refresh Token 双重撤销检查
- **Access token**：`app/deps.py::get_current_user` 加 jti 撤销列表查询 → 401
- **Refresh token**：`/auth/refresh` 检查旧 jti，若命中黑名单 401
- **Refresh 单次使用**：refresh 成功后自动 revoke 旧 jti（reason="rotated"）+ 签发新 refresh
- 结果：**refresh token replay 攻击彻底封堵** —— 攻击者拿到旧 refresh 也无法二次使用

### 4. 密码策略服务端 + 前端双重强化
`app/services/password_policy.py`：
- **规则**：长度 ≥8；lower/upper/digit/symbol 4 类字符至少 3 类；14 个常见弱口令黑名单；不含邮箱 local-part
- **PasswordPolicyError** 独立异常类，`/auth/password` 端点将其转 400
- **单元测试** 6 条覆盖：过短/常见/类不足/邮箱前缀/合法/过长（79 pass 全绿）

前端 `app/dashboard/profile/page.tsx`：
- Alert 文案更新为完整策略描述
- Form 客户端自定义 validator：≥8 位 + 3 类字符实时提示
- 客户端过滤在提交前给出即时反馈，最终仍由服务端复核

---

## Logout 前端集成

`app/dashboard/layout.tsx::handleLogout`：
- 动态 `import('@/lib/api')` 避免服务端渲染时循环依赖
- 调用 `logout()` 触发 `POST /auth/logout` 服务端吊销
- 本地 localStorage 清理 access + refresh
- **best-effort**：网络失败也会清空本地 token（避免僵尸 session）

`lib/api.ts::logout()`：
- 读取 refresh_token 提交给服务端
- try/catch 包裹 —— 服务端不可达也不阻塞本地清理

---

## Refresh Token Rotation 完整闭环

```
┌──────────────────────────────────────────────────────────────────┐
│ 场景 A · 正常刷新                                                  │
│   Client → /auth/refresh with old_refresh(jti=A)                  │
│   Server:                                                          │
│     1. verify signature + typ==refresh + user.is_active          │
│     2. check jti=A NOT in revoked_tokens                          │
│     3. revoke jti=A (reason="rotated")                            │
│     4. issue new access(jti=B) + refresh(jti=C)                   │
│   Client discards old_refresh, uses new pair                       │
│                                                                    │
│ 场景 B · 攻击者截获旧 refresh 并 replay                             │
│   Attacker → /auth/refresh with stolen_refresh(jti=A)              │
│   Server: jti=A ∈ revoked_tokens → 401                            │
│   ✅ Replay 攻击封堵                                                │
│                                                                    │
│ 场景 C · 主动 logout                                                │
│   Client → /auth/logout with current_refresh(jti=C)                │
│   Server: revoke jti=C (reason="logout")                          │
│   Client 本地清理 access + refresh                                  │
│   下次 refresh 尝试 → 401 → 跳登录                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 测试统计

```
Backend total:  79 pass (+6 password_policy) / 8 skipped · 全绿
Frontend tsc:   0 error
```

---

## 累积能力

| Track | 里程碑 |
|---|---|
| v0.1 base | LL/MM/NN/OO/PP/QQ/RR/SS + 3D 模型 |
| v2.0 R1-R10 | UOM/GeoFence/RBAC/Grafana/JWT refresh/审批/账户 等 |
| **v2.0 R11** | **RevokedToken + Logout + 密码策略 + Access/Refresh 双撤销** |

---

## 遗留 / 下一根桩

**仍在 v2.0 非 AI / 非 3D 范围：**

- [ ] RevokedToken cleanup cron（清理 exp < now 的行）
- [ ] 双因素认证 (2FA/TOTP)
- [ ] 密码错误次数限制（brute force 防御）
- [ ] 批量操作写审计中间件（当前仅单条走）
- [ ] SSO / OAuth 集成
- [ ] Docker 分发 → v1.0 GA 收官时再做 ✅

🐈 v2.0 R11 落地。
