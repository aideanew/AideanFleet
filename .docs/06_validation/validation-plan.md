# Validation Plan · 验证计划与完成定义

> 类型：validation ｜ 状态：active ｜ 建立：2026-09-22 ｜ 基线：HEAD `eb7a63c`
>
> 回答三个问题：**是否真的完成？怎么证明？证据在哪？**

---

## 1. 三层分离（不要合并）

```text
Task        做了什么
Validation  是否真的完成并满足要求
Evidence    用什么证明
```

**Task 完成 ≠ Task 已验证。** 这是本项目最严格的纪律。

---

## 2. 完成定义（Done）

```text
Done = Implementation + Acceptance + Verification + Evidence
```

四者缺一不可：

| 层 | 要求 |
| --- | --- |
| Implementation | 代码/配置实际变更完成 |
| Acceptance | 验收条件逐条满足，可客观判定 |
| Verification | 验证**已实际执行**（不是推断、不是"应该通过"） |
| Evidence | 证据已保存且可定位 |

---

## 3. 验证等级（四级，按证据强度）

| 等级 | 名称 | 说明 | 适用 |
| --- | --- | --- | --- |
| L1 | 静态检查 | 代码/配置审查，未运行 | 仅限说明性改动；不足以判定 DONE |
| L2 | 单元测试 | 隔离环境运行测试 | 大部分原子任务 |
| L3 | 集成验证 | 真实链路（DB/JSONL/Gate/调度） | 涉及一致性、并发、计量的任务 |
| L4 | 端到端/真实环境 | 浏览器、真实 CLI、真实 SMTP | W10 及发布前验收 |

**证据等级不匹配时必须显式声明。** 例如"L2 通过"不能用来声称"真实执行体可用"。

---

## 4. 标准验证命令（本项目实际口径）

> 取自执行方案 §5.1–5.4，路径为 Windows 绝对路径口径，跨平台兼容属 W1/W10 任务范围。

### 4.1 单测（标准形态）

```powershell
& 'E:\Code\AideanFleet\.venv\Scripts\python.exe' -m pytest -p no:cacheprovider '<绝对测试路径>' -q --tb=short
```

### 4.2 集成闭环测试（真实 intake/scheduler/dispatcher/Gate/SQLite/JSONL/usage 扫描，仅执行体与审查模型为替身）

```powershell
& 'E:\Code\AideanFleet\.venv\Scripts\python.exe' -m pytest -p no:cacheprovider 'E:\Code\AideanFleet\tests\core\test_intake_to_done_integration.py' -q --tb=short
```

> 该测试证明**模板闭环与计量归属**，**不证明**需求语义正确，也不覆盖 HTTP/浏览器/真实 CLI。

### 4.3 选择回归（最后实跑记录：77 passed / 16 warnings / 12.79s）

```powershell
& 'E:\Code\AideanFleet\.venv\Scripts\python.exe' -m pytest -p no:cacheprovider 'E:\Code\AideanFleet\tests\core\test_intake_to_done_integration.py' 'E:\Code\AideanFleet\tests\core\test_intake.py' 'E:\Code\AideanFleet\tests\core\test_scheduler.py' 'E:\Code\AideanFleet\tests\core\test_ten_scenarios.py' 'E:\Code\AideanFleet\tests\core\test_dag.py' 'E:\Code\AideanFleet\tests\core\test_context_budget.py' 'E:\Code\AideanFleet\tests\core\test_memory.py' 'E:\Code\AideanFleet\tests\governance\test_governance.py' 'E:\Code\AideanFleet\tests\rel\test_recovery_matrix.py' -q --tb=short
```

警告为既有 `datetime.utcnow` 弃用。**该数字不是性能压测结论。**

### 4.4 前端类型检查

```powershell
& 'E:\Code\AideanFleet\fleet\console\web\node_modules\.bin\vue-tsc.cmd' --noEmit -p 'E:\Code\AideanFleet\fleet\console\web\tsconfig.json'
```

### 4.5 提交前格式检查

```bash
git diff --check
```

> Vite build 不是类型检查的替代。构建与 E2E 须在 W10 隔离服务就绪后运行。

---

## 5. 每项原子任务的验证执行方法（强制口径）

沿用执行方案 §3.0 的五个四级动作：

```text
.a  增加一个行为测试
.b  运行并记录真实结果（已有该行为则记录通过，不造红灯）
.c  最小实现
.d  运行目标测试及相关回归
.e  同步契约 / 证据，并提交独立评审
```

**判定规则**：新增行为先记录失败 → 实现后退出码 0 → 最后相关回归**无新增失败**。
"无新增失败" ≠ "全绿"。既有失败须如实登记，不得掩盖。

---

## 6. 证据规范

证据必须满足：**可检查、可定位、与任务相关、尽可能可复现、不依赖口头解释**。

### 6.1 证据落点

| 类型 | 落点 |
| --- | --- |
| 既有工作包证据 | `reports/<WORK-PACKAGE>-evidence.md` |
| 新证据（本体系） | `.docs/06_validation/evidence/EVD-NNN/` |
| 运行时产物证据 | 按 attempt 隔离（见 `docs/契约/任务状态机.md`） |

### 6.2 证据目录形态

```text
EVD-001/
├── screenshot.png
├── test-result.md
├── execution-log.txt
└── output.json
```

### 6.3 证据引用要求

证据必须记录：命令原文、cwd、退出码、时间、内容摘要。
**不得把输出尾部文件称为完整证据。**

---

## 7. 验证结论取值

| 结论 | 含义 |
| --- | --- |
| `PASS` | 全部验收条件满足 |
| `FAIL` | 存在未满足条件 |
| `PARTIAL` | 部分满足，必须列出剩余项 |
| `BLOCKED` | 因外部/内部原因无法验证 |

---

## 8. 禁止事项（本项目已明确记录）

以下做法在本项目历史中已明确否决，验证环节不得再犯：

1. **不得使用尚不存在的 API 路径**作为可执行步骤
2. **不得根据旧 PID 直接停止进程**
3. **不得将其他会话生成的截图当作本轮验证**
4. **不得把 Vite build 当类型检查的替代**
5. **不得把"有模块"等同于"全部分层已兑现"**
6. **不得由 Fake/替身验收推断真实执行"从未"发生**
7. **不得直接指向用户正在使用的 5000/5050 服务**做 E2E——须在 W10 隔离服务就绪后运行
8. **不得把"测试通过"当"验收通过"**：既有测试不能代替真实需求理解、浏览器与外部执行体验收（证据 E20）
9. **不得用轮询次数或秒数**代替一致性证明
10. **不得在缺 usage 时以 0 冒充**——`unknown` 与 `0` 必须区分（证据 E09）

---

## 9. 当前已知验证边界（如实登记）

核验结论（2026-09-22），来自执行方案 §5.5 与 §6：

| 项 | 状态 |
| --- | --- |
| 真实事件字段与旧格式兼容映射 | ✅ 已完成 |
| 五任务 DONE 及项目/任务/角色/模型计量归属的隔离集成测试 | ✅ 已完成 |
| W6/3.6.1 事件计量幂等 | 🚧 **部分完成**：同一事件流重复扫描已验证 |
| 跨流身份隔离 | ❌ 未验证 |
| 历史重复账目对账迁移 | ❌ 未验证 |
| 旧格式文件轮转 | ❌ 未验证 |
| 多进程迁移 | ❌ 未验证 |
| 全量测试基线 | ❌ 尚无统一出口（依赖口径见证据 E19） |
| 浏览器全量 E2E | ❌ 未运行 |
| 真实模型调用 / 真实执行体任务 / SMTP 发送 | ❌ 未执行 |
| 性能压测 / 故障攻击复现 | ❌ 未执行 |

**最新相关回归**：新增测试文件两项 + 既有治理 28 项 = **30 passed / 16 warnings / 4.91s**；`git diff --check` 通过。
此前 77 项是字段映射修复时点的较大选择回归，**不是**幂等修复后的全量结果。

---

## 10. 验证记录模板

```markdown
# VAL-001：验证记录

## 1. 基本信息

- ID：VAL-001
- Task：TASK-NNN（运行时 T-NNN）
- Requirement：REQ-F-NNN
- Solution：SOL-NNN
- Reviewer：
- 日期：

## 2. Verification Target

验证什么？

## 3. Verification Method

如何验证？给出完整命令原文与 cwd。

## 4. Expected Result

预期结果是什么？

## 5. Actual Result

实际结果是什么？（退出码、耗时、警告数）

## 6. Result

- PASS / FAIL / PARTIAL / BLOCKED

## 7. Evidence

- 路径：

## 8. Issues

发现的问题：

## 9. Conclusion

验证结论。**必须声明证据等级（L1–L4）与覆盖边界。**
```

---

## 11. 独立验收（W10 出口）

发布前必须由独立身份完成验收：

* 集成任务完成后再开放终局验收（证据 E02）
* **不可由同一执行身份自审同一交付**（对应候选 REQ-NF-405）
* 未覆盖的需求不得宣告项目完成

---

## 12. 更新规则

* 新增验证等级或命令口径 → 更新本文件，并同步任务模板 §9
* 验证失败 → 不得修改验收条件迁就结果，须如实登记并回到 Task
* 发现"验收条件与实际实现不一致" → 这属于需求变化，走 `product-requirements.md` 流程
