# INT-04 执行报告（INT-04R 返工修订版）

> **任务**: 集成验收（执行器烟雾、五模式走查、并发压测、Phase 2 验收）
> **日期**: 2026-09-15
> **状态**: ✅ 全部完成（0 failed）

---

## 本机实测证据

### pytest 原样输出

```
178 passed, 70 warnings in 34.71s
```

### CLI 双口径实测（2026-09-15 本机）

**PowerShell 口径**（测试运行环境）:

```
PS> claude --version
2.1.272 (Claude Code)

PS> codex --version
codex-cli 0.153.4

PS> opencode --version
1.18.31

PS> hermes --version
Hermes Agent v0.21.1 (2026.9.7) · upstream 05d705dd
Install directory: C:\Users\EDY\AppData\Local\hermes\hermes-agent
Install method: git
Python: 3.11.16
OpenAI SDK: 2.24.0
Update available: 1347 commits behind — run 'hermes update'
```

**shutil.which 检测**:

| CLI | shutil.which | 路径 |
|-----|-------------|------|
| claude | ✅ | `C:\Users\EDY\AppData\Roaming\npm\claude` |
| codex | ✅ | `C:\Users\EDY\AppData\Roaming\npm\codex` |
| opencode | ✅ | `C:\Users\EDY\AppData\Roaming\npm\opencode` |
| hermes | ✅ | `C:\Users\EDY\AppData\Local\hermes\bin\hermes.exe` |

**注意**: 以上为 2026-09-15 本机 PowerShell 环境实测。CLI 可用性取决于安装状态，可能因环境变化而不同。

---

## 交付物

### 1. tests/int/_cli_probe.py（新增）
- 共享 CLI 探测工具，`shutil.which()` + skip 模式
- 与 tests/core/test_resolve_integration.py 口径一致

### 2. tests/int/test_integration验收.py（修订）
- TestExecutorSmoke 使用 `_cli_probe.skip_if_unavailable()` 替代硬编码 `shell=True`
- CLI 不可用时 skip（reason = 实测结论），不再 fail

### 3. tests/int/__init__.py（新增）
- 支持相对导入

---

## 测试结果

| 维度 | 数量 | 状态 |
|------|------|------|
| GOV-01 治理层 | 28 | ✅ |
| INT-04 集成验收 | 28 | ✅ |
| 原有测试 | 122 | ✅ |
| **合计** | **178** | **✅ 0 failed** |

---

## 执行器烟雾探测（本机实测）

| 执行器 | 版本 | 状态 | 证据来源 |
|--------|------|------|----------|
| Claude Code | 2.1.272 | ✅ | `claude --version` 原样输出 |
| Codex CLI | 0.153.4 | ✅ | `codex --version` 原样输出 |
| OpenCode | 1.18.31 | ✅ | `opencode --version` 原样输出 |
| Hermes | v0.21.1 | ✅ | `hermes --version` 原样输出 |

CLI 调用次数：4/5（约束 ≤ 5）

---

## 五模式走查

| 模式 | 状态 |
|------|------|
| plan | ✅ |
| run | ✅ |
| intake | ✅ |
| audit | ✅ |
| discuss | ✅ |
| invalid 拒绝 | ✅ |

---

## 并发压测

| 场景 | 线程数 | 状态 |
|------|--------|------|
| 并发派发 | 5 | ✅ |
| 并发用量记录 | 20 | ✅ |
| 并发预算检查 | 20 | ✅ |

---

## Phase 2 端到端验收

14 个场景全部通过：
1. 治理层存储初始化
2. 用量记录写入
3. 预算池创建
4. 预算熔断器触发
5. 审批门创建
6. 审批门批准
7. 审批门拒绝
8. 报表生成
9. Fake 适配器能力查询
10. Fake 适配器执行
11. 统一启动入口导入
12. 预算同步
13. 多模式派发
14. 并发适配器执行

---

## 约束验证

| 约束 | 状态 | 说明 |
|------|------|------|
| CLI 调用 ≤ 5 | ✅ | 实际 4 次 |
| SMTP 发送 ≤ 3 | ✅ | **BLOCKED** — 凭据缺失，未执行任何真实 SMTP 发送 |
| 仅修改 tests/int/ | ✅ | 新增 _cli_probe.py、__init__.py |
| skip 口径统一 | ✅ | 与 test_resolve_integration.py 一致 |

---

## SMTP 状态定版

**状态**: BLOCKED（原因：凭据缺失）

- 当前未配置 SMTP 凭据（.env 中无 SMTP_HOST/SMTP_USER/SMTP_PASS）
- 审批门模块已实现，但未触发真实发送
- 所需凭据清单：SMTP_HOST、SMTP_PORT、SMTP_USER、SMTP_PASS、SMTP_FROM
- 状态取值：`BLOCKED(凭据缺失)`

---

## 撤回声明清单

| 原声明 | 处理 | 原因 |
|--------|------|------|
| "28 passed" | 修订为 "178 passed" | 原口径仅含 INT-04 测试，未计入全量回归 |
| CLI 版本号无本机证据 | 补充双口径实测输出 | 本次返工补充了 PowerShell 原样输出 |
| "SMTP 0/3" | 明确为 BLOCKED(凭据缺失) | 原表述未说明原因 |
