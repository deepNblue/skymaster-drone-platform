# SkyMaster · v2.0 Compliance Track R19 · 三员分立

> 2026-07-10 11:15 UTC · Track D 第二根桩
> 规格书 §3.11 · 等保 2.0 三级 SoD (Separation of Duty)

---

## 🎯 核心机制

**"三员分立"** 是等保 2.0 三级过审硬性要求：

| 角色 | 中文 | 职责 | 严禁 |
|---|---|---|---|
| `system_officer` | 系统员 | 配置、部署、备份 | 授权、审计 |
| `security_officer` | 安全员 | 授权、密钥、策略 | 系统运维、审计 |
| `audit_officer` | 审计员 | 只读日志、生成报表 | 任何写操作 |

**四条铁律：**
1. 一个自然人只能持一种三员身份
2. `admin` 账号**不得兼任**三员身份（业务超管 vs 合规三员必须分离）
3. **只有安全员**可以授予/撤销三员身份（无自我提权）
4. 高危操作（如 `backup.restore`、`key.destroy`）要求**双人协签**，且两人身份必须不同

---

## ✅ 本轮五件套

### 1. User 表新增 `officer_role` 列 · Alembic 0013
- 与业务 `role` **正交** — 不覆盖 admin/operator/viewer
- NULL 表示普通用户
- 加索引便于按官员身份枚举

### 2. Permission Matrix `officer_matrix.py`
显式的操作 → 允许角色映射：

```python
"officer.grant":     {"security_officer"}           # 只有安全员可授权
"users.write":       {"system_officer", "admin"}
"compliance.toggle": {"security_officer", "admin"}  # admin 保留 grace 期
"audit.read":        {"audit_officer", "admin"}
"audit.export":      {"audit_officer"}              # admin 也不行
"keys.rotate":       {"security_officer"}
"backup.restore":    {"system_officer", "security_officer"}  # 双人协签
```

**核心函数：**
- `can(user, action)` — 布尔判断
- `require_action(action)` — FastAPI dependency 工厂
- `require_officer(*officers)` — 直接按 officer_role 卡
- `validate_officer_assignment(target, new)` — 校验 admin 不可叠加
- `dual_control_check(actor, cosigner, action)` — 双人协签校验

### 3. REST API 5 端点 `officers.py`
| 端点 | 权限 | 说明 |
|---|---|---|
| GET `/admin/officers` | list officer | 列出所有三员 |
| GET `/admin/officers/matrix` | list officer | 暴露完整权限矩阵 |
| POST `/grant` | **security_officer only** | 授权（校验 SoD） |
| POST `/revoke` | **security_officer only** | 撤销 |
| POST `/dual-sign` | any auth | 双人协签校验（demo） |

所有 grant/revoke/dual-sign 操作**都进审计** — 谁给谁授了什么身份有据可查。

### 4. Compliance 端点也接入 SoD
`compliance.toggle` 的权限从"仅 admin"扩展为"安全员或 admin (grace)"，未来可通过配置 flag 关闭 admin grace。

### 5. 前端 `/dashboard/officers` 三员管理页
- 三员职责说明卡（系统员/安全员/审计员，颜色区分）
- **当前三员分布** 表格 + 撤销按钮
- **权限矩阵** 完整表格（15+ 操作 × 角色）
- 指派 Modal：user_id 输入 + 三员身份选择
- **铁律提示** Alert：admin 不可兼任 · 唯一授权者是安全员 · 高危操作双人协签
- 侧栏菜单新增

---

## 测试统计

```
Backend: 147 pass (+12 officer_matrix) / 8 skipped · 全绿
Frontend: tsc 0 error
```

**12 新增用例：**
1. Matrix 数据结构
2. `can()` 布尔判断（安全员/审计员/系统员/admin 交叉）
3. 未知操作默认 deny
4. 校验 admin 不可兼任 officer (409)
5. 校验非法 officer_role
6. `dual_control_check` 5 种失败姿势
7. 安全员成功授权 audit_officer
8. admin 尝试授权 → 403
9. 授权给 admin → 409
10. 自我授权 → 403
11. 撤销 officer 成功
12. Dual-sign 双方相同 officer_role → 403

---

## 规格书 §3.11 对齐

| 需求 | 状态 |
|---|---|
| 三员分立（系统/安全/审计） | ✅ officer_role 列 + 权限矩阵 |
| 权限矩阵按操作细粒度控制 | ✅ 15+ 操作显式映射 |
| 高危操作双人协签 | ✅ dual_control_check |
| admin/business 与 officer 正交 | ✅ 硬拦截 admin + officer 叠加 |
| 授权操作可审计 | ✅ 全部进 audit_log |
| SM3 哈希链 + SM4 加密（R18） | ✅ |
| 国密可选（用户诉求） | ✅ |
| SM2 数字签名 | ⏳ 下一根桩 |

---

## 下一根桩（Track D · R20）

- [ ] **SM2 密钥对生成 + 数字签名**（可抗抵赖）
- [ ] 关键操作签名验证（如飞行报备批准、密钥轮换）
- [ ] KMS/HSM 集成接口预留（当前仍是 pure-Py）
- [ ] 或转 Track B **Vision AI Edge Runtime**（用户 ROI 排序 ③）

🐈 v2.0 Track D · R19 落地。等保 2.0 三级 SoD 骨架完备。
