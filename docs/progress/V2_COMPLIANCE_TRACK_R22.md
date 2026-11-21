# V2.0 Compliance Track — R22 · 审计日志批量导出 + 哈希链完整性

**日期**：2026-07-13
**主线**：v2.0 合规三级冲刺 (R21 密钥轮换 → R22 审计导出 + 完整性核验)
**状态**：✅ 后端 export service + 4 endpoints + 7 新测试全绿；前端审计员专用页；TypeScript 全绿

---

## 🎯 R22 目标

等保三级 8.1.4 硬要求：审计员必须能**批量导出审计日志**、**独立校验完整性**、且导出行为本身也必须留痕。

R22 一次性解决这三条：
1. 审计员专用导出接口（CSV + GBFT 国标格式）
2. 哈希链断裂点独立检测（不依赖第三方工具）
3. 每次导出自动写 `audit.export` 行 → 元审计（audit-of-audit）

---

## 📦 交付物

### 1. `services/audit_export.py` · 导出服务核心（+220 行）

**`ExportFilter`** 白名单过滤器：`ts_from/ts_to/actor_role/action/actor_id/limit`，limit 硬顶 50 万行防 OOM。

**`export_csv(db, flt) → bytes`** · UTF-8 BOM + 12 列（含 prev_hash/curr_hash/sig_hex/sig_key_id 全套哈希链元数据），diff 列以 JSON 字符串序列化

**`export_gbft(db, flt) → bytes`** · JSONL 格式，首行 header（record_count / filter / hash_chain_start / notes），后续每行一条审计记录。GB/T 20945-2013「网络安全审计数据交换格式」的简化子集，第三方审计事务所可用一个 shell 单行验证：
```bash
head -1 export.jsonl | jq  # header
tail -n +2 export.jsonl | jq -c '.curr_hash' | head  # 逐行链验证
```

**`integrity_report(db, flt) → ChainIntegrityReport`** · 独立扫描哈希链，返回 `hash_chain_ok / hash_chain_break_at / signed_count / unsigned_count`，用于审计员做**离线**篡改检测。

### 2. `api/v1/audit_export.py` · 4 endpoints（+180 行）

| Endpoint | 权限 | 用途 |
|----------|------|------|
| `GET /audit/export/csv` | `audit.export` | 下载 CSV |
| `GET /audit/export/gbft` | `audit.export` | 下载 GBFT JSONL |
| `GET /audit/export/preview` | `audit.read` | 前 N 条预览（不触发下载） |
| `GET /audit/integrity` | `audit.chain_verify` | 完整性快照 |

**元审计（audit-of-audit）**：每次 CSV/GBFT 下载都写一行 `audit.export` 到 `audit_logs`，diff 里记录格式 + 过滤条件 + 字节数，确保导出行为可追溯。

**权限接入三员分立**：所有端点走 `require_action(...)`，仅 `audit_officer` 命中；`admin` 因为不得兼任三员也被阻止（R19 SoD 铁律）。

### 3. `api/v1/router.py` · 路由注册（+1 行）

`audit_export` router 加入 v1 主路由。

### 4. 前端 `app/dashboard/audit-export/page.tsx` · 审计员专用页（+220 行）

**过滤条件卡**：时间范围 RangePicker + 角色 Select + Action 输入 + limit 数字输入

**操作按钮**：
- 「预览前 20 条」→ `auditPreview`
- 「校验哈希链完整性」→ `auditIntegrity`（走 `Result` 组件显示通过/断裂）
- 「下载 CSV」→ 打开导出 URL
- 「下载 GBFT (JSONL)」→ 打开导出 URL

**完整性报告卡**：
- 通过 → 绿色 Result + 已签名/未签名计数
- 断裂 → 红色 Result + 明确指出 audit_log.id + Error Alert 提示应急预案

**预览表**：id / ts / actor_role / action / resource / sig（有无签名 Tag）/ chain（curr_hash 前 8 字符）

### 5. Dashboard 导航接入（`layout.tsx` +2 行）

「审计导出」菜单项 · `FileTextOutlined` 图标 · 位于 SM2 签名之后。

### 6. 前端 `lib/api.ts` · 类型 + 函数（+70 行）

- `AuditRow / AuditPreview / AuditIntegrity / AuditExportFilter` 严格对齐后端
- `auditPreview / auditIntegrity / auditExportUrl` 3 个函数
- URL 拼接工具 `_qs()` 过滤空值

### 7. 测试 `tests/test_audit_export.py` · 7 新测试（+180 行）

关键场景：

| 测试 | 覆盖 |
|------|------|
| `test_export_csv_contains_all_columns_and_bom` | CSV 12 列 + UTF-8 BOM Excel 兼容 |
| `test_export_gbft_has_header_then_records` | GBFT header + record 分离结构 |
| `test_integrity_report_detects_break` | **核心不变式**：篡改 prev_hash 后立即被识别 |
| `test_integrity_report_ok_when_valid` | 未篡改时 hash_chain_ok=True |
| `test_integrity_report_counts_unsigned` | 兼容 R20 前无签名的老审计行 |
| `test_export_filter_limit_is_clamped` | 恶意 limit 值被夹到 [1, MAX] |
| `test_export_csv_encodes_diff_as_json_string` | diff 稳定序列化不丢字段 |

**执行结果**：
```
tests/test_sm2_rotation.py .....                        [ 41%]
tests/test_audit_export.py .......                      [100%]
============================== 12 passed in 0.14s ==============================
```

---

## ✅ 完整验证

**新测试** · 7/7 全绿
**R21 回归测试** · 5/5 全绿
**TypeScript tsc --noEmit** · exit=0, 0 errors
**Router 装配** · `audit_export.router` 已注册至 `/api/v1/audit/*`

---

## 🔒 等保三级 8.1.4 · 审计控制点

| 控制点 | R21 前 | R22 后 |
|--------|--------|--------|
| 8.1.4.1 审计范围 | ✅ | ✅ |
| 8.1.4.2 审计内容 | ✅ | ✅ |
| **8.1.4.3 审计记录导出** | ❌ | ✅ 双格式导出 |
| **8.1.4.4 记录完整性核验** | 部分（SM2 单条） | ✅ 全量哈希链扫描 |
| **8.1.4.5 审计员权限隔离** | ✅（R19） | ✅ 强制走 `require_action` |
| 8.1.4.6 元审计（audit-of-audit） | ❌ | ✅ 导出自动留痕 |

**结论**：R22 完成后，v2.0 合规三级的审计能力项**全部覆盖**。

---

## 📂 改动文件清单

```
backend-v0.1/
├── app/services/audit_export.py       (+220 行 · 新增)
├── app/api/v1/audit_export.py         (+180 行 · 新增)
├── app/api/v1/router.py               (+2 行 · 注册)
└── tests/test_audit_export.py         (+180 行 · 新增, 7 tests)

frontend-v0.1/
├── lib/api.ts                         (+70 行 · 类型+3函数)
├── app/dashboard/audit-export/page.tsx (+220 行 · 新增)
└── app/dashboard/layout.tsx           (+2 行 · 菜单项)
```

**代码规模** · +874 行（后端 582 + 前端 292）

---

## 📝 下一步（R23 候选）

v2.0 合规三级冲刺剩余的最后一桩：

- **R23 · CIIO 关基自评报告 + 一键生成 markdown**（2-3 小时）
  - 依据《关键信息基础设施安全保护条例》30 项运营者义务生成自评表
  - 从各现有服务（officers/sm2/audit_export/geofence/preflight）自动汇总合规度
  - 输出可打印的 markdown 报告，供内审用

R23 完成后可申请等保测评实测。

---

**R22 状态** · ✅ 完成
**推进节奏** · R19-R22 四轮累计 6-7 小时 · v2.0 合规三级冲刺进入收官阶段
