# V2.0 Compliance Track — R21 · SM2 密钥轮换 + HSM 接入预留

**日期**：2026-07-13
**主线**：v2.0 合规三级冲刺 (R20 SM2 前端 → R21 密钥轮换 + HSM 抽象)
**状态**：✅ 后端 rotation + HSM 抽象 + 5 新测试全绿；前端补 rotation/hsm 两个卡；TypeScript 全绿

---

## 🎯 R21 目标

R20 完成 SM2 抗抵赖前端上桩后，还有两项等保三级硬要求悬着：

1. **密钥定期轮换**：等保三级要求关键密钥 90 天必须轮换，且**老密钥仍需能验证历史审计**（否则历史抗抵赖失效）
2. **HSM 接入预留**：生产上私钥必须在密码机内，不能出现在 env 变量里

R21 一次性解决这两个问题，且保证不停机、可增量迁移。

---

## 📦 交付物

### 1. `services/sm2_signer.py` · KeySet 元数据升级

**新增字段**（每个 KeySet）：
- `created_at`（unix 秒 · 0 = 未知 legacy）
- `active`（默认 True · 老密钥可设 False → 仅验证不签新）
- `lifetime_seconds`（默认 90 天 · 每密钥可覆盖）

**新增 env 支持**：
- `SM2_KEY_LIFETIME_DAYS` · 全局密钥生命周期
- `SM2_KEY_CREATED_AT` · ISO8601 创建时间
- `SM2_RETIRED_KEY_IDS` · 逗号分隔 · 标记密钥仅验证不签新
- `SM2_KEYS_JSON` 每条 entry 现支持 `created_at`/`active`/`lifetime_days`

**新增 API 函数**：
- `key_info(key_id)` · 单密钥富元数据
- `rotation_status()` · 全密钥快照 + `any_rotation_due` 汇总

**语义强化**：
- `active_key_id()` 现在只返回 `active=True` 且有私钥的密钥
- 老密钥被 retire 后，`sign_hash` 自动切下一个可用活密钥
- 老密钥的公钥仍在密钥集合内 → 历史审计行仍能 verify

### 2. `services/hsm.py` · 新增 HSM 抽象层（+220 行）

**核心设计**：`SM2SignerBackend` 抽象基类 + 两个具体实现

**`EnvHexSigner`**（priority=10, 默认可用）
- 读取环境变量私钥（当前 R20 baseline）
- `is_available() → sm2_signer.is_enabled()`

**`PKCS11Signer`**（priority=100, 默认关闭）
- 仅在 `SM2_HSM_ENABLED=1` 且 `PyKCS11` 可导入时激活
- 当前 `sign()` 返回 None → 回落到 env-hex
- 已注释真实 HSM 接入的 4 步（slot/pin/label/mechanism），vendor 提供驱动后即可展开

**门面函数**：
- `sign_via_best_backend(...)` · 按 priority 依次尝试
- `verify_via_any_backend(...)` · 任一后端验证通过即返回 True
- `hsm_status()` · 返回所有后端可用性快照

### 3. `api/v1/crypto_sm2.py` · 新增 2 endpoints

- `GET /crypto/sm2/rotation` · rotation snapshot（有 rotation_due 汇总）
- `GET /crypto/sm2/hsm` · HSM backend 可用性

### 4. 前端 `crypto-sm2/page.tsx` · 补两张卡（+130 行）

- **密钥轮换卡**：表格展示每密钥的 age_days / lifetime_days / active / rotation_due；有到期时置顶告警
- **HSM 后端卡**：表格展示 backends 优先级 + 当前 active_backend；Info 提示 PKCS#11 生产接入路径

### 5. 测试 `tests/test_sm2_rotation.py` · 5 新测试

- `test_key_metadata_reports_age_and_rotation_due` · 100 天老密钥被正确标记 rotation_due
- `test_retired_key_not_used_for_new_signs` · retired v1 → 签新用 v2；同时 v1 老签名仍能验证（**核心不变式**）
- `test_hsm_status_env_only_when_no_hsm` · 默认返回 env-hex 唯一可用
- `test_signer_facade_uses_env_backend_when_hsm_disabled` · sign_via_best_backend 走 env-hex 端到端
- `test_pkcs11_opt_in_falls_through_when_not_provisioned` · 打开 HSM 开关但驱动缺失时优雅回落

**执行结果**：
```
tests/test_sm2_rotation.py .....                        [100%]
5 passed in 0.06s
```

---

## ✅ 完整验证

**新测试** · 5/5 全绿
**TypeScript tsc --noEmit** · exit=0, 0 errors
**前端 layout tsc** · exit=0（R20 遗留菜单项无损）

（**Note**：`tests/test_sm2_signer.py` 的 4 个 error 来自 `model_deployments/model_listings.org_id` FK 指向未定义 `organizations` 表 — 属于 R19 前的 Model Marketplace 建模遗留，非本轮引入，与 SM2 无关。这些测试用 `create_all` 建库触发 FK 校验；纯逻辑的 SM2 sign/verify 5 个测试仍全绿。）

---

## 🔒 等保三级对应控制点

| 控制点 | R20 前 | R20 后 | R21 后 |
|--------|--------|--------|--------|
| 传输/存储完整性 | ✅ | ✅ | ✅ |
| 抗抵赖签名 | ⚠️ 仅后端 | ✅ 端到端可视 | ✅ |
| 第三方可验证 | ⚠️ 需手工 | ✅ 公钥可导出 | ✅ |
| **密钥定期轮换** | ❌ | ❌ | ✅ 元数据+API+UI |
| **HSM/密码机接入** | ❌ | ❌ | ✅ 抽象层就绪 |
| 密钥生命周期告警 | ❌ | ❌ | ✅ any_rotation_due |

---

## 📂 改动文件清单

```
backend-v0.1/
├── app/services/sm2_signer.py       (+87 行 · 元数据字段/rotation API)
├── app/services/hsm.py              (+220 行 · 新增)
├── app/api/v1/crypto_sm2.py         (+45 行 · rotation+hsm endpoints)
└── tests/test_sm2_rotation.py       (+150 行 · 新增, 5 tests)

frontend-v0.1/
├── lib/api.ts                       (+40 行 · rotation/hsm 类型+函数)
└── app/dashboard/crypto-sm2/page.tsx (+130 行 · 两张新卡)
```

**代码规模** · +672 行（后端 502 + 前端 170）

---

## 📝 下一步（R22 候选）

R21 完成后剩余的 v2.0 合规三级冲刺桩：

- **R22 · 审计日志批量导出 + GBFT 格式**（4-5 小时）· 等保三级必须提供审计导出接口
- **R23 · 关基 CIIO 自评报告 markdown**（2 小时）· 关键信息基础设施 30 项义务自评

**推荐做 R22** · 因为审计导出是审计员日常刚需，比 CIIO 自评的一次性文档更有工程价值。

---

**R21 状态** · ✅ 完成
**推进节奏** · R19 → R20 → R21，5-6 小时 · 距 v2.0 合规三级完整闭环还剩 2 桩
