# 进度追踪

> 版本：v1.0  日期：2026-09-24
> 上游：.docs/04_planning/current-plan.md, .docs/02_requirements/backlog.md
> 下游：.docs/06_reports/
> 关联 ADR：ADR-023

---

## 一、当前状态

| 指标 | 数值 |
|------|------|
| 版本 | 0.3.0 |
| Phase | Phase 2（建设期收尾·正确性优先） |
| 基线 HEAD | eb7a63c → 5c96888 |
| 工作包 | 10 个（W1-W10） |
| 三级原子任务 | 58 项 |
| 测试通过 | 276 passed, 0 failed, 21 skipped |
| 前端 | Vue3 + Vite + Pinia |

---

## 二、Phase 1 完成项（✅）

- [x] 控制面核心：状态机、DB、事件、计划
- [x] Manager：intake、dispatcher、scheduler
- [x] 控制台：FastAPI + WebSocket + 7 页前端
- [x] 启动器：launch_core 统一启动
- [x] 执行体适配器：opencode/codex/claude
- [x] 契约冻结：状态机 v1.1、字段 v1.0、API v1.1、events v1.0
- [x] 锁屏与 token 验证
- [x] 三级大纲与进度展示

---

## 三、Phase 2 进行项

### 已完成（✅）
- [x] CORE-02：控制台重建（FastAPI + WS）
- [x] CORE-03：契约体系与 ADR 裁决
- [x] 前端类型检查通过
- [x] 集成测试通过
- [x] ADR-024~030：7 设想评估完成

### 进行中（🔄）
- [ ] W1-W10 工作包 58 项任务逐项推进
- [ ] 7 个测试失败修复
- [ ] 异常处理（BLOCKED/ESCALATED）完善
- [ ] 用量与预算（governance.db）完善

### 待办（⬜）
- [ ] Prompt 模板系统实现（ADR-024）
- [ ] 模型任务间切换实现（ADR-028）
- [ ] CLI 安装脚本（ADR-027）
- [ ] 主流程文档验证（ADR-030）

---

## 四、测试状态

| 类别 | 通过 | 失败 | 跳过 |
|------|------|------|------|
| 单元测试 | 269 | 7 | 21 |
| 端到端 | - | - | - |

### 失败测试清单

全部修复 ✅ — 原因均为跨平台路径处理问题（intake.py 硬编码 Windows 反斜杠）。

修复内容：
1. `intake.py` — `_workspace_allowed()` / `start_project()` / `detect_launch_intent()` 使用 `os.path.normpath` + `os.sep` 替代硬编码 `\`
2. `intake.py` — 添加 Linux 绝对路径正则模式（原仅匹配 Windows 驱动器路径）
3. `cli_start.py` — `default_project_name()` 跨平台 basename 提取
4. `test_confirm_no_block.py` — 使用 TestClient 上下文管理器 + mock find_project

---

## 五、变更日志

| 日期 | 变更 | ADR |
|------|------|-----|
| 2026-09-24 | 7 设想评估完成 | ADR-024~030 |
| 2026-09-24 | 创建评审标准指令文档 | - |
| 2026-09-24 | 优化目录结构（Makefile/.local/.gitignore） | - |
| 2026-09-24 | 更新 AGENTS.md 为项目专属规范 | - |
| 2026-09-24 | 创建端到端主流程文档 | ADR-030 |
| 2026-09-24 | 创建用户场景文档 | - |
