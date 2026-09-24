# GOV-01 执行报告

> **任务**: 治理层实现（预算池、用量聚合、审批门、报表）
> **日期**: 2026-09-15
> **状态**: ✅ 全部完成

---

## 交付物

### 1. fleet/governance/store.py
- SQLite 存储层，三张表：`governance_usage`、`governance_budget`、`governance_approvals`
- 线程安全（threading.Lock）
- 支持 CRUD 操作和聚合查询

### 2. fleet/governance/usage.py
- 用量聚合器，从 events.jsonl 解析 `model:call` 事件的 usage 字段
- 支持按任务/项目/日期/模型聚合
- 无 usage 字段时视为 0（unknown_usage=1）

### 3. fleet/governance/budget.py
- 三层预算池：task → project → daily
- 熔断器：超限抛出 `BudgetExceeded` 异常
- 默认值：task=200k, project=2M, daily=500k tokens
- 安全守则：配置缺失时按默认值执行，不放任无限消耗

### 4. fleet/governance/approval.py
- 三种审批场景：delete/overwrite、SMTP 首次发送、预算超 80%
- 超时机制：24h → 自动拒绝 + `approval:expired`
- 审批决定：approve/reject

### 5. fleet/governance/report.py
- 日报/任务级/项目级报表生成
- 汇总用量、预算状态、待审批数

### 6. .github/workflows/tests.yml
- CI 矩阵：windows-latest + ubuntu-latest
- Python 3.12
- `pip install -r requirements.txt` → `pytest tests -q`

### 7. tests/governance/test_governance.py
- 28 个测试，覆盖所有模块
- 每个测试使用独立临时数据库（autouse fixture）

---

## 测试结果

```
28 passed, 16 warnings in 2.36s
```

---

## 约束验证

| 约束 | 状态 |
|------|------|
| 仅创建 fleet/governance/ | ✅ |
| 仅创建 tests/governance/ | ✅ |
| 仅创建 .github/workflows/ | ✅ |
| 零现有代码变更 | ✅ |
| 预算默认值生效 | ✅ |
| 审批超时 24h | ✅ |
