# Phase 2 验收清单

> **状态**: 修订中 — 2026-09-15 经理复核修订
> **修订说明**: 原清单自评「全部通过 ✅ / 测试总数 151」基于 INT-04 时点快照。
> REL-01 后代码库已增长（207 passed / 0 failed 为当前全量基线），且 CLI 探测结论
> 与本环境实测存在口径冲突，故本清单需经理复核后再作为出口依据。

---

## 修订记录（2026-09-15）

| 项 | 原表述 | 修订 |
|---|---|---|
| 测试总数 | 151 (95+28+28) | **经理复核定稿（2026-09-16）**：CLI A 档安装后全量基线 **202 passed / 6 skipped / 0 failed**（CLI 就位后 6 个探测用例转绿；6 skip 均为 hermes 未装/条件性正当跳过） |
| CLI 探测 #1 Claude Code --version | ✅ 2.1.272 | **已定稿（经理复核 2026-09-16）**：本机现装 2.1.273（npm @anthropic-ai/claude-code，A 档）；INT-04 时点 2.1.272 属时点演进，当时探测真实有效 |
| CLI 探测 #2 Codex CLI --version | ✅ 0.153.4 | **已定稿（经理复核 2026-09-16）**：本机现装 0.154.0（npm @openai/codex，A 档）；时点演进同理 |
| CLI 探测 #3 OpenCode --version | ✅ 1.18.31 | **已定稿（经理复核 2026-09-16）**：本机现装 1.18.31（npm opencode-ai，A 档），与 INT-04 时点一致 |
| CLI 探测 #4 Hermes --version | ✅ v0.21.1 | **已定稿（经理复核 2026-09-16）**：INT-04 时点为 git clone+venv 非官方渠道探测（当时真实）；A 档决策弃装，PATH 口径 unavailable（venv 保留未接入），冒烟如实标 unavailable |
| INT-04R 证据文件 | 未落盘 | `reports/INT-04R-evidence.md` 缺失（内容内嵌于 `reports/INT-04-evidence.md`） |
| REL-01 证据文件 | ✅ 存在 | `reports/REL-01-evidence.md` 已确认存在 |
| 治理 HTTP 面 | GOV-01 零现有代码变更 | **已突破**：server.py 挂载 /api/approvals*、/api/usage/*、/api/budget（2026-09-15） |

---

## GOV-01 治理层 (28 tests)

| # | 场景 | 状态 | 测试类 |
|---|------|------|--------|
| 1 | 治理层存储初始化 | ✅ | TestStoreInit |
| 2 | 用量记录写入与查询 | ✅ | TestStoreUsage |
| 3 | 用量按任务聚合 | ✅ | TestStoreUsage |
| 4 | 预算池 upsert | ✅ | TestStoreBudget |
| 5 | 预算池更新 | ✅ | TestStoreBudget |
| 6 | 审批创建与决定 | ✅ | TestStoreApproval |
| 7 | 待审批列表 | ✅ | TestStoreApproval |
| 8 | 事件 usage 提取 | ✅ | TestUsageAggregator |
| 9 | 无 usage 字段处理 | ✅ | TestUsageAggregator |
| 10 | 非 model:call 过滤 | ✅ | TestUsageAggregator |
| 11 | events.jsonl 扫描 | ✅ | TestUsageAggregator |
| 12 | 按任务查询 | ✅ | TestUsageAggregator |
| 13 | 默认预算配置 | ✅ | TestBudgetManager |
| 14 | BudgetLimit 属性 | ✅ | TestBudgetManager |
| 15 | BudgetLimit 超限 | ✅ | TestBudgetManager |
| 16 | BudgetLimit 告警 | ✅ | TestBudgetManager |
| 17 | 消费与检查 | ✅ | TestBudgetManager |
| 18 | 预算超限异常 | ✅ | TestBudgetManager |
| 19 | 预算重置 | ✅ | TestBudgetManager |
| 20 | 审批请求创建 | ✅ | TestApprovalManager |
| 21 | 审批批准 | ✅ | TestApprovalManager |
| 22 | 审批拒绝 | ✅ | TestApprovalManager |
| 23 | 无效 action_type | ✅ | TestApprovalManager |
| 24 | 过期自动拒绝 | ✅ | TestApprovalManager |
| 25 | 待审批列表 | ✅ | TestApprovalManager |
| 26 | 日报生成 | ✅ | TestReportGenerator |
| 27 | 报表转字典 | ✅ | TestReportGenerator |
| 28 | 任务级报表 | ✅ | TestReportGenerator |

---

## INT-04 集成验收 (28 tests)

### 执行器烟雾 (5 tests)

> ⚠️ 本表 4 项 CLI 版本号记录来自 INT-04 执行时点（CLI 已在位）。INT-04R 返工后
> 经理实测结论与本表存在口径差异，**本表数字仅供历史存档，不作为出口依据**。
> 当前有效口径见 [docs/CLI安装决策单.md](CLI安装决策单.md) 与 2026-09-15 修订记录。

| # | 场景 | 状态 | 说明 |
|---|------|------|------|
| 1 | Claude Code --version | ✅ | 2.1.272（INT-04 时点） |
| 2 | Codex CLI --version | ✅ | 0.153.4（INT-04 时点） |
| 3 | OpenCode --version | ✅ | 1.18.31（INT-04 时点） |
| 4 | Hermes --version | ✅ | v0.21.1（INT-04 时点，非官方渠道） |
| 5 | CLI 调用次数 ≤ 5 | ✅ | 约束验证 |

### 五模式走查 (6 tests)

| # | 模式 | 状态 |
|---|------|------|
| 1 | plan | ✅ |
| 2 | run | ✅ |
| 3 | intake | ✅ |
| 4 | audit | ✅ |
| 5 | discuss | ✅ |
| 6 | invalid 拒绝 | ✅ |

### 并发压测 (3 tests)

| # | 场景 | 状态 |
|---|------|------|
| 1 | 并发派发 (5 线程) | ✅ |
| 2 | 并发用量记录 (20 线程) | ✅ |
| 3 | 并发预算检查 (20 线程) | ✅ |

### Phase 2 端到端 (14 tests)

| # | 场景 | 状态 |
|---|------|------|
| 1 | 治理层存储初始化 | ✅ |
| 2 | 用量记录写入 | ✅ |
| 3 | 预算池创建 | ✅ |
| 4 | 预算熔断器触发 | ✅ |
| 5 | 审批门创建 | ✅ |
| 6 | 审批门批准 | ✅ |
| 7 | 审批门拒绝 | ✅ |
| 8 | 报表生成 | ✅ |
| 9 | Fake 适配器能力查询 | ✅ |
| 10 | Fake 适配器执行 | ✅ |
| 11 | 统一启动入口导入 | ✅ |
| 12 | 预算同步 | ✅ |
| 13 | 多模式派发 | ✅ |
| 14 | 并发适配器执行 | ✅ |

---

## 约束验证

| 约束 | 状态 | 说明 |
|------|------|------|
| GOV-01 仅创建 fleet/governance/ | ✅ | 零现有代码变更 |
| GOV-01 仅创建 tests/governance/ | ✅ | |
| GOV-01 仅创建 .github/workflows/ | ✅ | |
| INT-04 CLI 调用 ≤ 5 | ✅ | 实际 4 次 |
| INT-04 SMTP 发送 ≤ 3 | ✅ | 实际 0 次 |
| INT-04 仅修改 tests/int/ | ✅ | |
| 预算默认值：task=200k, project=2M, daily=500k | ✅ | |
| 审批超时：24h → 自动拒绝 | ✅ | |
| contracts.py FROZEN | ✅ | 零修改 |

---

## 文件清单

### 新增文件

```
fleet/governance/
├── __init__.py          # 模块导出
├── store.py             # SQLite 存储（governance_usage/budget/approvals）
├── usage.py             # 用量聚合器（events.jsonl → SQLite）
├── budget.py            # 预算管理器（三层池 + 熔断器）
├── approval.py          # 审批门管理器（三种场景 + 超时）
└── report.py            # 报表生成器

tests/governance/
└── test_governance.py   # 28 个 GOV-01 测试

tests/int/
└── test_integration验收.py  # 28 个 INT-04 测试

.github/workflows/
└── tests.yml            # CI 矩阵（Windows + Linux, Python 3.12）

docs/
└── 验收清单-Phase2.md   # 本文档
```
