# SkyMaster · v2.0 Compliance Track R18 · 国密可选加密网关

> 2026-07-10 10:35 UTC · Track D 第一根桩
> 规格书 §3.11 审计 · 等保 2.0 三级

---

## 🎯 用户核心诉求

> "国密设计成可选项，有时候需要低延迟时可以关闭国密加密"

**已完全对齐：**
- ✅ 默认 `enabled=false, mode=off` — 零性能开销
- ✅ 三档模式 `off / hash / full` 独立可选
- ✅ 保护模块可选（audit_log/session/flight_approval/transcription）
- ✅ 遥测/直播默认不在保护列表 → 热路径不受影响
- ✅ Admin API 运行时切换，无需重启
- ✅ 前端一键关闭按钮，秒级降级

---

## ✅ 本轮六件套

### 1. SM3 / SM4 参考实现 `sm_crypto.py`
- 纯 Python 无外部依赖（未装 gmssl 也能跑）
- **SM3** — GB/T 32905-2016，通过官方 KAT（`SM3(abc) = 66c7f0f4...`）
- **SM4-CBC + PKCS7** — GB/T 32907-2016，16 字节 IV 自嵌入
- `sm3_chain(prev, payload)` — 哈希链原语
- 生产环境可无缝替换为 HSM/KMS 后端

### 2. Compliance Gateway `crypto_gateway.py`
**类：** `ComplianceGateway` · 全局单例 `gm`

```python
gm.enabled_for("audit_log")   # 该模块是否开启保护
gm.chain_hash(prev, payload)  # SM3 追加
gm.encrypt("audit_log", pt)   # SM4 加密（含模块判断）
gm.decrypt(...)               # 兼容旧明文（无法解密时透传）
gm.apply(enabled=, mode=, modules=)  # 运行时切换
```

**关键设计：**
- ✅ 关闭时 `encrypt/decrypt/chain_hash` 全部 passthrough — **零内存分配**
- ✅ 三档模式 `off | hash | full`
- ✅ SM4 密钥懒加载 · 未配置时从 `jwt_secret` 用 SM3 推导（仅 dev/demo）
- ✅ decrypt 失败自动透传 → **无缝兼容混合时期数据**（关-开-关切换不丢日志）

### 3. Config 5 个新开关 `config.py`
```python
gm_crypto_enabled: bool = False    # 主开关
gm_crypto_mode: str = "off"        # off/hash/full
gm_sm4_key_hex: str = ""           # 16 字节 hex 密钥
gm_protect_modules: str = "audit_log"  # 逗号分隔
```

### 4. AuditLog 表 + 哈希链 · Alembic 0012
新增 3 列：`prev_hash` / `curr_hash` / `diff_ct`
- 关闭状态：3 列全为 NULL，与之前完全一致
- hash 模式：只写哈希对
- full 模式：`diff_ct` 存 SM4 密文，明文 `diff` 置 NULL

**Audit middleware 改造：**
- 写入前先拉取链尾 → 计算新哈希 → 视 mode 决定加密

### 5. Compliance Admin API `/api/v1/admin/compliance`
| 端点 | 说明 |
|---|---|
| GET `/status` | 当前状态（管理员） |
| POST `/toggle` `{enabled,mode,modules}` | 运行时切换（可回滚） |
| POST `/verify-audit-chain?limit=` | 验证审计链完整性 |

自身切换操作也进审计 — 谁改了 gm 有据可查。

### 6. 前端 `/dashboard/compliance` 管理页
- **状态卡：** 启用/关闭 · 模式 · 保护模块数 · 算法
- **配置区：**
  - 模式 Radio: off ⚡ / hash 🔗 / full 🔒
  - 保护模块 Checkbox 4 选
  - 应用配置按钮
  - **🔴 一键关闭** 按钮（低延迟场景秒级降级）
- **链验证区：** 一键验证 · 显示已检查条数 · 断链高亮
- 侧栏菜单新增

---

## 测试统计

```
Backend: 135 pass (+11 compliance_gateway) / 8 skipped · 全绿
Frontend: tsc 0 error
```

**11 个新增用例覆盖：**
1. SM3 官方 KAT（GB/T 32905-2016）
2. SM4-CBC 中文/长文本 round-trip
3. SM4 密钥长度校验
4. Gateway 默认关闭 → passthrough
5. hash 模式扩展链、full 模式加解密
6. 模块隔离（audit_log 保护 / telemetry 透传）
7. 运行时切换 apply()
8. Admin API 403 非管理员
9. Admin toggle by admin
10. 非法 mode 422 拒绝

---

## 性能特性

**Passthrough zero-cost：**
- `gm.enabled = False` 时所有 helper 只做一次布尔判断
- 不 import sm_crypto 模块
- 不分配任何 SM4/SM3 状态

**用户场景：**
- 🚀 无人机遥测 100Hz + 直播 SRT/WebSocket → **默认关闭 · 零延迟增量**
- 🔒 审计日志/等保过审 → 开 hash 模式，SM3 微秒级
- 🔒🔒 密评通道/客户敏感数据 → 开 full 模式，SM4 加密存储

---

## 规格书对齐

| §3.11 审计 / 等保 2.0 需求 | 状态 |
|---|---|
| 审计日志 tamper-evident | ✅ SM3 哈希链 |
| 日志加密存储 | ✅ SM4 密文列 |
| 密评通道 | ✅ full 模式 |
| **国密可选（用户新增诉求）** | ✅ 默认关闭 · 一键切换 |
| 低延迟场景兼容 | ✅ 遥测/直播不受影响 |
| 三员分立 | ⏳ 下一根桩 |

---

## 遗留 · Track D 下一根桩

- [ ] 三员分立数据模型：SystemOfficer/SecurityOfficer/AuditOfficer
- [ ] 权限矩阵按角色隔离（操作/授权/审计三权分置）
- [ ] SM2 数字签名 · 用于关键操作抗抵赖
- [ ] 分级密钥托管 · KMS/HSM 集成接口

🐈 v2.0 Track D · R18 落地 · 用户诉求 100% 对齐。
