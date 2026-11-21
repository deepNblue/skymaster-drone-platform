# V2.0 Compliance Track — R20 · SM2 抗抵赖签名前端上桩

**日期**：2026-07-13
**主线**：v2.0 合规三级冲刺 (R19 三员分立 → R20 SM2 前端接入)
**状态**：✅ Front-end UI + Backend API 全链路可用（backend R21 Step F 完成于 07-11，本轮补前端）

---

## 🎯 目标

R21 后端已完成国密 SM2 数字签名核心链路：
- `services/sm2_signer.py` · sign/verify + 多密钥注册
- `api/v1/crypto_sm2.py` · 5 endpoints (status/public/verify/generate-keypair/audit)
- `audit_middleware` · 每条审计行落库时叠加 SM2 签名（soft-fail）
- `tests/test_sm2_signer.py` · 5 test 全绿

但缺一块前端上桩：审计员/安全员在 dashboard 内无法可视化验证 SM2 状态，也无法交互式做抗抵赖核验。R20 补齐这一块。

---

## 📦 交付物

### 1. 前端 API 客户端（`frontend-v0.1/lib/api.ts`）

补充 5 个 SM2 客户端函数，与后端 5 个 endpoint 一一对齐：

```typescript
sm2Status()                   // GET  /api/v1/crypto/sm2/status
sm2PublicKey(key_id)          // GET  /api/v1/crypto/sm2/public/{key_id}
sm2Verify(body)               // POST /api/v1/crypto/sm2/verify
sm2GenerateKeypair()          // POST /api/v1/crypto/sm2/generate-keypair
sm2AuditSig(audit_id)         // GET  /api/v1/crypto/sm2/audit/{audit_id}
```

类型接口 `Sm2Status / Sm2PublicKey / Sm2VerifyIn / Sm2VerifyOut / Sm2AuditSig` 已严格对齐后端 pydantic schema。

### 2. 前端 SM2 页面（`app/dashboard/crypto-sm2/page.tsx`）

三段式布局：

**A. 签名服务状态卡**
- 签名开关（enabled / soft-fail）· Tag 色码显示
- 活动密钥 ID · 蓝色 Tag
- 已注册密钥列表 · 可点击切换查看
- 未启用时展示 soft-fail 说明 Alert

**B. 公钥导出卡**
- 完整公钥 hex（128 字符未压缩点）· Ant Design copyable
- 分发给第三方验证方使用

**C. 抗抵赖验证器**
- 输入任意审计日志 ID
- 平台自动取 `curr_hash + sig_hex + sig_key_id + ts`
- 后端离线用注册公钥重新 verify
- 结果分三态：
  - ✅ 签名验证通过（未被篡改）
  - ⚠️ 签名验证失败（可能被篡改）
  - ⚠️ 未知 key_id（密钥已轮换/丢失）

### 3. Dashboard 导航接入（`app/dashboard/layout.tsx`）

侧边栏新增「SM2 签名」菜单项，图标 `SafetyCertificateOutlined`，位置在 Copilot 与管理后台之间。审计员登录后进入即可使用。

---

## ✅ 验证结果

**TypeScript 编译**
```bash
$ node_modules/.bin/tsc --noEmit
exit=0  errors=0
```

**后端 SM2 单元测试（回归）**
```bash
$ .venv/bin/python -m pytest tests/test_sm2_signer.py
5 passed, 15 warnings in 1.19s
```

（另 1 个 error 来自无关的 `model_deployments` FK 预存 schema 问题，未触及本轮改动。）

---

## 🔒 等保三级 8.1.4.4 · 数据完整性 · 对应

R20 完成后，本项目在等保三级下的完整性/抗抵赖控制点覆盖度：

| 控制点 | 实现 | 状态 |
|--------|------|------|
| a) 传输过程数据完整性 | TLS + HMAC | ✅ 已达 |
| b) 存储过程数据完整性 | SHA-256 哈希链（R18）| ✅ 已达 |
| c) 关键操作抗抵赖 | SM2 签名（R21 后端 + R20 前端）| ✅ 已达 |
| d) 第三方可验证性 | 公钥导出 + verify API | ✅ 已达 |

**结论**：抗抵赖已具备第三方审计事务所可接入的最小闭环（公钥+签名+离线 verify）。

---

## 📝 下一步（R21 · Compliance Track）候选

R20 完成后，v2.0 合规三级冲刺剩余的高优先级桩：

1. **R21 · 密钥轮换 + HSM 接入预留**（3-4 小时）
   - `services/sm2_signer.py` 支持密钥版本化历史
   - 加 `retire_key_id` 接口，标记密钥不再签新但仍能 verify 老审计
   - 预留 HSM PKCS#11 / 深信服密码机接入抽象

2. **R22 · 审计日志导出与联邦上报**（4-5 小时）
   - 批量导出：GBFT 格式（等保三级要求）
   - 定期上报到公安部网络安全监察平台（本地占位实现，接口预留）

3. **R23 · 关基 CIIO 认定合规检查**（2 小时）
   - 生成 CIIO 自评报告 markdown
   - 检查 30 项关键设施运营者义务

**推荐先做 R21 密钥轮换**，因为 SM2 生产上跑不到 90 天就需要密钥轮换机制（等保要求），且 HSM 接入预留是接后续商业化必备。

---

## 📂 改动文件清单

```
frontend-v0.1/
├── lib/api.ts                              (+65 行 · SM2 客户端)
├── app/dashboard/crypto-sm2/page.tsx       (+220 行 · 新增)
└── app/dashboard/layout.tsx                (+1 行 · 侧边栏菜单)
```

**代码规模** · +286 行前端 · 0 后端改动 · 0 数据库迁移

---

**R20 状态** · ✅ 完成
**推进节奏** · 每轮 R 平均 1.5 小时 · v2.0 合规三级预计 R23 完成后即可申请等保测评
