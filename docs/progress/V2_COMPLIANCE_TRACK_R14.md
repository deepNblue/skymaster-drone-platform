# SkyMaster · v2.0 Compliance Track (R14) 登录事件审计 · 异常登录检测 · 用户/管理员双端 UI

> 2026-07-10 05:52 UTC · R13 之后继续
> 范围严格锁死：**非 AI / 非 3D-4D**

---

## ✅ 本轮三件套

### 1. LoginEvent 模型 + Alembic 20260710_0008
`app/models/login_event.py`：
- **字段**：id / user_id FK SET NULL / email / method / outcome / ip / country / user_agent / extra JSONB / created_at
- **method 枚举**：`password` / `sso:google` / `sso:github` / `refresh` / `logout` / `totp`
- **outcome 枚举**：`success` / `invalid_email` / `invalid_password` / `invalid_totp` / `locked` / `rate_limit` / `deactivated`
- **4 个索引**：user_id / outcome / ip / created_at（分析查询友好）
- FK ondelete=SET NULL 保留匿名审计记录（用户被删除仍可查历史）

### 2. 全链路事件记录
`app/services/login_recorder.py` + `/auth/login` 8 处切点：
| 场景 | outcome |
|---|---|
| IP 限流触发 | `rate_limit` |
| email 不存在 | `invalid_email` |
| 账号锁定 | `locked` |
| 账号停用 | `deactivated` |
| 密码错 | `invalid_password` |
| TOTP/备份码错 | `invalid_totp` |
| 全部通过 | `success` |

**Best-effort 写入**：`record_login()` 单独 try/except，DB 失败不影响主认证流程。

### 3. 异常登录检测
`app/services/anomaly_detector.py`：
- **`geoip_lookup(ip)`** — 内置轻量 CIDR 启发式（可 monkeypatch 换 MaxMind）
- **`check_anomaly(session, user_id, ip)`** — 三级检测：
  1. `NEW_COUNTRY` — 新 IP + 新国家（30 天窗口内首次出现）
  2. `IMPOSSIBLE_TRAVEL` — 上次成功 <5 分钟前来自不同国家（物理不可能）
  3. `NEW_IP` — 新 IP + 已知国家（soft warn）
- **`notify_admin(email, anomaly, ip)`** — 环境变量 `ANOMALY_WEBHOOK_URL` 配 POST JSON，未配置则仅 logger.warning
- 集成到 `/auth/login` success 分支，异常不阻塞登录（异步通知模式）

单元测试 7 条：LAN 判定 / CN+US IP 识别 / 无历史不报警 / 同 IP 不报警 / 新国家报警 / 物理不可能 / 新 IP 同国家 soft warn

---

## 事件读取 API

`app/api/v1/auth_events.py`：
- **`GET /auth/login-events/me`** — 普通用户查自己最近 20 条（`limit ≤ 100`）
- **`GET /auth/login-events`** — 管理员全局浏览
  - Query: `outcome` / `email` / `ip` / `since_hours` (1-720) / `limit` (1-1000)
- **`GET /auth/login-events/stats`** — 管理员聚合统计
  - 返回 `{total, success, failed, by_outcome{}}`

---

## 前端 UI

### 用户端：`/dashboard/login-history`
- 表格展示最近 50 次认证事件
- 时间/方式/结果/IP/国家/UA 六栏
- **outcome 彩色 Tag**：success 绿 / password 错红 / locked 火山色 / rate_limit 橙
- **method emoji 化**：🔑 密码 / 🔢 2FA / 🅶 Google / 🐙 GitHub / ♻️ 刷新 / 🚪 登出
- **警告条**：失败次数 >0 → 弹 Alert 提示"建议改密码开 2FA"
- 侧边栏新增 "登录历史" 菜单项（SafetyOutlined 图标）

### 管理员端：`/admin/login-analytics`
- **4 个 Statistic Card**：总尝试 / 成功 / 失败 / 失败率百分比
- **失败率 >30% 变红** 提示存在暴破攻击
- **表格 + 3 类过滤**：时间窗口 (1h/24h/7d/30d) + outcome + email 模糊
- 支持 200 条分页 30/页浏览
- 刷新按钮手动重载

---

## 测试统计

```
Backend total:  108 pass (+7 anomaly_detector) / 8 skipped · 全绿
Frontend tsc:   0 error
```

---

## 安全能力矩阵累积

| Track | 里程碑 |
|---|---|
| R10 | JWT refresh token + rotation |
| R11 | 密码策略 + Revocation list + Logout |
| R12 | 2FA/TOTP + Lockout + 常量时间 |
| R13 | Backup code + IP 限流 + OAuth2 SSO |
| **R14** | **登录事件审计 + 异地/异常国家/物理不可能检测 + 双端 UI** |

---

## 遗留 / 下一根桩

**仍在 v2.0 非 AI / 非 3D 范围：**

- [ ] SAML 2.0（企业用户）
- [ ] 邮件/短信告警对接 SMTP 或 Twilio
- [ ] MaxMind GeoIP 数据库集成
- [ ] Redis 版 rate_limit（多实例）
- [ ] 批量操作审计中间件
- [ ] Password reset via email (forget-password flow)
- [ ] Docker 分发 → v1.0 GA 收官时再做 ✅

🐈 v2.0 R14 落地。
