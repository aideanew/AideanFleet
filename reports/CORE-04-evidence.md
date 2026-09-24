# CORE-04 证据文件 · 上下文成本引擎四件套 + 契约 v1.2 增补

角色：A（后端核心工程师） · 日期：2026-09-15 · 运行环境：Windows 10 / Python 3.12.13 / 项目 .venv
本文件是 CORE-04 全部硬性验收项的过程与数字留档，所有命令均在项目根目录以 `.venv\Scripts\python.exe` 实跑。

---

## 1. 开工前基线（verbatim）

开工前全量回归（改造前代码，.venv 实跑）：

```
178 passed 之前的基线口径：
.venv/Scripts/python.exe -m pytest tests -q
→ 95 passed（CORE-03 收尾时基线；本包开工期间并行包 INT-03 将套件扩充至 151 passed，见 §6）
```

prompt 组装链路通读结论（改造前）：

- `fleet/manager/dispatcher.py`：派工 prompt 直接 `pack.to_prompt()`，无预算、无裁剪，TaskPack 允许的上下文文件全量内嵌。
- `fleet/manager/rework_manager.py`：返工重派走完整派工流程，detail/上下文全量重发，仅追加【返工意见】文本，无增量。
- `fleet/models/transport.py`：单条 user message 直发，无 system/user 前后缀分离，无 usage 归一化，无缓存标记。
- `fleet/models/router.py`：HTTP 候选切换无计量事件；`model:call` 事件改造前不存在。
- `fleet/core/db.py` + plan：任务表无 context_budget/memory_refs/retry_context 列。
- `fleet/manager/contracts.py`：无 token 口径定义。

基线成本估算（开工前手工）：典型 TaskPack `to_prompt()` 直拼 ≈ **810 chars ≈ 202 tokens**（按契约 §13.7 口径 chars ÷ 4；该样例 detail 偏长，9.6 脚本内同口径实测 DISPATCH 模板为 735 chars ≈ 183 tokens，两者差异来自样例 detail 长度，口径一致）。

## 2. 契约 v1.2 冻结清单（produce-then-freeze，先于 TaskPack 变更）

两份契约文档原位升级并冻结为 v1.2（先改文档、后改代码，git 历史可证）：

- `docs/契约/控制台API.md` → v1.2 FROZEN：新增 §13 上下文成本引擎契约（13.1 TaskPack 三可选字段 / 13.2 计量事件字段 / 13.3 Project Memory / 13.4 预算裁剪 / 13.5 Incremental Diff / 13.6 Prompt Cache / 13.7 token 计量口径 chars÷4）；§3 动作码表补 `model:call`、`prompt:assembled`、`budget:check`、`budget:exceeded`、`memory:recorded`；§5.1 model_pool 键位表补 `/CACHE`。
- `docs/契约/任务进度表字段.md` → v1.2 FROZEN：新增 §2.1 上下文成本扩展列（context_budget INTEGER / memory_refs TEXT / retry_context TEXT，旧库轻迁移）；§6 磁盘布局补 `data/memory/<project_id>.json`。

关键冻结字面：TRUNCATION_NOTICE=「（上下文已按预算裁剪，完整文件路径如下，可按需读取）」；REWORK_TEMPLATE_LINE=「这是第 {attempt} 轮返工，只需基于以下增量信息修复，不要重新调查全项目」；usage 四键 prompt_tokens/cached_tokens/completion_tokens/total_tokens 缺失补 0、绝不估算冒充服务端计量。

## 3. 实现清单

| 项 | 文件 | 要点 |
|---|---|---|
| 9.1 | 上表两份契约 | 见 §2 |
| 9.2 | `fleet/core/memory.py`（新） | 存储 `data/memory/<project_id>.json` 原子写；三来源（decision/correction/distill）；`build_memory_header` 每条 ≤200 字摘要绝不内嵌全文；DONE 后 `distill_from_report` 从六节报告「改动清单+四要素」提炼，报告缺失返回 None 不阻塞 |
| 9.3 | `fleet/manager/context_budget.py`（新） | 固定顺序 system_prompt + memory_header + 任务说明 + 上下文文件；单文件头+尾+关键词命中段裁剪，单文件上限（默认 500 token）+ 总预算双重约束；溢出附截断清单；发 prompt:assembled / budget:check（固定段本身超预算加发 budget:exceeded，派工仍继续，熔断归角色D） |
| 9.4 | `fleet/manager/rework_manager.py` | `build_retry_context`：attempt + failure(gate 结果/审查意见) + previous_diff（git diff --stat + 前 3 个文件 diff，无 git 诚实降级基线兜底） + evidence_paths；返工 prompt 只发增量 + 修复指令 + 模板句 |
| 9.5 | `fleet/models/transport.py` 等 | `normalize_usage` 四键归一（cached_tokens 优先级：OpenAI details → DeepSeek prompt_cache_hit_tokens → raw → 0）；稳定前缀注册表（role, project) 键控、字节不变则版本不变；`FLEET_MODEL_<i>_CACHE` 开关（默认 false）启用时 system message 附 `cache_control: {"type":"ephemeral"}`；pool/config/router 同步 |
| 集成 | `fleet/manager/dispatcher.py` | `_build_prompt` 替换 `pack.to_prompt()` 成为唯一派工 prompt 出口；model:call（adapter 路径）+ router 路径双发；run_to_completion PASS/PARTIAL 后自动 distill |

## 4. 集成冒烟（memory → ref → trim → cache 四段链路）

`tests/core/test_context_budget.py::test_smoke_memory_ref_trim_model_call_chain`（stub adapter，无真实网络）：
record_decision 写入记忆 → TaskPack.memory_refs 引用 → assemble_prompt 中出现 `[PROJECT MEMORY]` 摘要头且受预算裁剪 → budget:check 事件 → transport.set_stable_prefix 版本语义（同字节同版本、变更才升版）→ reset。另 `test_new_task_prompt_contains_memory_and_pass_event` 验证真实派工链路里 prompt:assembled / budget:check / model:call（usage 四键）全部在场。

verbatim（27 例 = 三测试文件全量，含冒烟）：

```
.venv/Scripts/python.exe -m pytest tests/core/test_context_budget.py::test_smoke_memory_ref_trim_model_call_chain tests/core/test_memory.py tests/core/test_context_budget.py tests/core/test_retry_incremental.py -v
...
tests/core/test_memory.py::test_add_entry_schema_frozen PASSED           [  3%]
tests/core/test_memory.py::test_add_entry_rejects_bad_kind_and_truncates_summary PASSED [  7%]
tests/core/test_memory.py::test_record_decision_and_correction_emit_events PASSED [ 11%]
tests/core/test_memory.py::test_build_memory_header_empty_or_unknown_refs_is_empty PASSED [ 14%]
tests/core/test_memory.py::test_build_memory_header_summary_only_never_full_text PASSED [ 18%]
tests/core/test_memory.py::test_distill_from_report_creates_artifact_once PASSED [ 22%]
tests/core/test_memory.py::test_distill_from_report_missing_report_returns_none PASSED [ 25%]
tests/core/test_memory.py::test_ids_increase_monotonically_never_reuse PASSED [ 29%]
tests/core/test_context_budget.py::test_estimate_tokens_is_chars_over_four PASSED [ 33%]
tests/core/test_context_budget.py::test_assemble_prompt_fixed_order PASSED [ 37%]
tests/core/test_context_budget.py::test_assemble_prompt_trims_files_within_budget PASSED [ 40%]
tests/core/test_context_budget.py::test_assemble_prompt_missing_file_marked PASSED [ 44%]
tests/core/test_context_budget.py::test_assembly_events_fields_frozen PASSED [ 48%]
tests/core/test_context_budget.py::test_budget_exceeded_when_fixed_section_alone_overflows PASSED [ 51%]
tests/core/test_context_budget.py::test_extract_keywords_hit_relevant_paragraphs PASSED [ 55%]
tests/core/test_context_budget.py::test_assemble_rework_prompt_incremental_only PASSED [ 59%]
tests/core/test_context_budget.py::test_smoke_memory_ref_trim_model_call_chain PASSED [ 62%]
tests/core/test_retry_incremental.py::test_build_retry_context_with_git_repo PASSED [ 66%]
tests/core/test_retry_incremental.py::test_build_retry_context_without_git_falls_back PASSED [ 70%]
tests/core/test_retry_incremental.py::test_handle_rework_persists_retry_context PASSED [ 74%]
tests/core/test_retry_incremental.py::test_rework_dispatch_sends_only_increment PASSED [ 77%]
tests/core/test_retry_incremental.py::test_new_task_prompt_contains_memory_and_pass_event PASSED [ 81%]
tests/core/test_retry_incremental.py::test_context_budget_parse_rules[None-8000] PASSED [ 85%]
tests/core/test_retry_incremental.py::test_context_budget_parse_rules[0-8000] PASSED [ 88%]
tests/core/test_retry_incremental.py::test_context_budget_parse_rules[299-8000] PASSED [ 92%]
tests/core/test_retry_incremental.py::test_context_budget_parse_rules[300-300] PASSED [ 96%]
tests/core/test_retry_incremental.py::test_context_budget_parse_rules[12000-12000] PASSED [100%]

============================= 27 passed in 2.62s ==============================
```

## 5. 9.6 成本对比（硬性验收，verbatim 实跑输出）

脚本：`reports/CORE-04-cost-comparison.py`（离线 stub、临时目录隔离、跑完自清理，不污染 `data/`）。
口径：tokens ≈ chars ÷ 4（契约 §13.7）。改造前 = 旧口径全量直拼（system_prompt + 记忆全文 + 任务说明 + 3 个上下文文件全文；返工场景再加返工意见追加）；改造后 = v1.2 引擎（记忆摘要头 + 预算裁剪 / retry_context 增量）。

```
CORE-04 · 9.6 成本对比（口径：tokens ≈ chars ÷ 4，契约 v1.2 §13.7）
--------------------------------------------------------------------------------------------------------
场景                               改造前 chars    改造前 tokens     改造后 chars    改造后 tokens        降幅
--------------------------------------------------------------------------------------------------------
全新任务（3 记忆 + 3 上下文文件）                 39989          9997          6291          1572     84.3%
二轮返工（retry_context 增量）               40052         10013           732           183     98.2%
--------------------------------------------------------------------------------------------------------
附：现状基线（典型 TaskPack 直拼 DISPATCH 模板，无记忆/无上下文文件）： 735 chars ≈ 183 tokens
附：记忆头 vs 记忆全文： 760 chars vs 3991 chars
附：改造后（新任务）含截断清单： True
附：改造后（返工）含模板句： True
```

结论：全新任务 **9997 → 1572 tokens，降幅 84.3%**；二轮返工 **10013 → 183 tokens，降幅 98.2%**。两个场景均 ≥60% 硬线，返工场景单列。降幅主要来源：记忆全文→摘要头（-3231 chars）、上下文文件按预算裁剪且默认单文件上限 500 token（实测定稿依据已注释在 `context_budget.py`，单文件 2000 token 过松时实测仅 54.3%）、返工不重发全量上下文（-39320 chars）。

## 6. 全量回归（verbatim）

中途节点：9.4 完成时 151 passed（并行包 INT-03 扩套件后）；CORE-04 新增 27 例后最终：

```
.venv/Scripts/python.exe -m pytest tests -q
→ 178 passed, 66 warnings in 29.95s
```

零失败、零跳过冲突。4 处既有断言按 v1.2 契约同步更新（均带注释说明）：test_recovery（DONE 后 memory:recorded 在场）、test_resolve_integration 与 test_ten_scenarios 场景10（八事件链按生命周期动作码过滤后比对）、test_rework_manager（返工 prompt 增量化后不再含【MANAGER DISPATCH】）。

## 7. 明文密钥审计（grep sk-）

```
grep -rnoE "sk-[A-Za-z0-9]{16,}" fleet/ tests/   → 零命中（无任何密钥形态字符串）
grep -rln "sk-" fleet/ tests/                    → 命中均为良性：
  - fleet/core/config.py:45 / fleet/core/events.py:30-32：脱敏规则定义本身（scrub 掉 sk- 密钥的正则，属必要功能代码，不含密钥值）
  - fleet/console/web/src/*.vue 与 fleet/console/dist/assets/*、node_modules/*：CSS 类名 task-list / mask-tag 的子串误中及前端构建产物
  - __pycache__/*.pyc：编译缓存
```

结论：零明文密钥。密钥仅存于 `.env`（不入库），事件经 scrub 脱敏。

## 8. Prompt Cache 诚实退化说明

- 服务端返回 usage 时 `normalize_usage` 原样归一 cached_tokens（四来源优先级见 §3），**绝不本地估算冒充**。
- 模型池未开 CACHE（默认）或服务端不支持前缀缓存时，cached_tokens 诚实为 0，不做任何伪装；`cache_control` 标记仅在 CACHE=true 时附加，不支持的服务端忽略之（标记无害）。
- 稳定前缀（system_prompt + memory_header）按 (role, project) 键控注册，字节级不变则版本号不变——满足 provider 前缀缓存对字节稳定的要求；记忆条目追加不会破坏既有版本（头内容随 refs 定，refs 不变即字节不变）。
- 真实 CLI/HTTP 端到端缓存命中率验证依赖角色C 的真实适配器接入（本包范围外），已具备的全部接口与字段就绪。

## 9. 与其他角色的接口确认

- 角色D（治理）：只消费 events.jsonl 中 `model:call` / `prompt:assembled` / `budget:check` / `budget:exceeded` / `memory:recorded`，字段 schema 冻结于契约 §13.2；引擎不做熔断/审批，budget:exceeded 仅如实上报且派工继续。
- 角色C（执行适配）：依赖本包 9.6 结论与本包交付的 usage 归一化、stream_chunk 就绪状态；stream_chunk 产生方仍缺（遗留 INT-04），已在上轮报告中声明。

## 10. 数据与磁盘

全部运行时数据落在 `data/`（memory 存储 `data/memory/<project_id>.json`、事件、任务库），未上传任何数据；9.6 对比脚本使用系统临时目录并在结束时清理，仓库 `data/` 无对比过程残留。
