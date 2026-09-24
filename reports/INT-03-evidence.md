# INT-03 交付证据

## 任务概述
- **任务ID**: INT-03
- **执行角色**: 角色C (Integration & Launch Engineer)
- **完成时间**: 2026-09-15 16:50
- **状态**: 已完成

## 完成的工作

### 1. BaseAdapter 桥接层重构
**文件**: `fleet/executors/base.py`

- 将 `BaseAdapter` 桥接到 `fleet/manager/contracts.py` 的契约
- 保持 `ErrorCode` 枚举作为内部工具
- 添加辅助函数: `save_evidence()`, `detect_error()`
- 更新 `register_adapter()` 同时注册到 `ADAPTER_REGISTRY` 和 `contracts._REGISTRY`

### 2. 适配器迁移
**文件**: `fleet/executors/fake.py`, `claudecode.py`, `codex.py`, `opencode.py`, `hermes.py`

- 将 `probe()` 方法重命名为 `capabilities()` (符合 contracts 契约)
- 修复 `run()` 方法签名: 移除额外的 `attempt` 和 `task_id` 参数
- 添加模块级 `Adapter` 别名 (供 `resolve()` 发现)
- 更新 `__init__.py` 导出新函数

### 3. 统一启动核心
**文件**: `fleet/launcher/launch_core.py` (新建)

- 创建 `LaunchRequest` 数据类 (project/mode/tasks/requirements/port/notes/model/seats/source)
- 实现 `launch_core()` 9步统一流程:
  1. env probe
  2. port precheck
  3. ensure_env_file
  4. start console
  5. start manager gateway
  6. health check
  7. project register SQLite only
  8. open browser 5000
  9. pull up watch_events_loop

### 4. CLI启动器修复
**文件**: `fleet/launcher/cli_start.py`

- **缺陷1**: 控制台脚本 → 改用 `python -m fleet.console.server`
- **缺陷2**: projects.json 双写 → 只写 SQLite projects 表
- **缺陷3**: 浏览器端口 → 改为 5000
- **缺陷4**: allowed_roots → 从 `.env` FLEET_ALLOWED_ROOTS 读取
- **缺陷5**: 端口默认值 → 改为 5000

### 5. Hermes入口修复
**文件**: `fleet/launcher/hermes_entry.py`

- **缺陷6**: 解析器改为逐行状态机，避免空行截断
- **缺陷7**: mode 白名单增加 `plan`
- **缺陷8**: allowed_roots → 从 `.env` FLEET_ALLOWED_ROOTS 读取

### 6. 测试文件
**文件**: `tests/int/test_resolve_chain.py` (新建)

- 9个测试用例覆盖:
  - resolve("fake") 正确返回 FakeAdapter
  - FakeAdapter.run() 正常成功返回
  - FakeAdapter.run() 429/401/TIMEOUT 错误
  - FakeAdapter.capabilities() 返回正确的 Capabilities
  - FakeAdapter 调用统计
  - BaseAdapter 是 contracts.BaseAdapter 的子类
  - FakeAdapter 是 contracts.BaseAdapter 的子类

### 7. 测试修复
**文件**: `tests/test_fake.py`, `tests/test_smoke.py`, `tests/test_cli_launch.py`, `tests/core/test_resolve_integration.py`

- 更新所有测试使用 `capabilities()` 替代 `probe()`
- 移除 `test_resolve_to_done_chain` 的 xfail 标记
- 修复签名合规测试

## 测试结果

```
95 passed, 45 warnings in 21.55s
```

所有测试通过，包括:
- `tests/int/test_resolve_chain.py` (9个新测试)
- `tests/core/test_resolve_integration.py::test_resolve_to_done_chain` (原xfail，现已通过)
- 所有现有测试

## 关键修复

### contracts.resolve() 兼容性
- 模块级 `Adapter` 别名使 `resolve("fake")` 能正确发现适配器
- `register_adapter()` 装饰器同时注册到 `contracts._REGISTRY`
- `isinstance()` 检查现在通过 (FakeAdapter 继承自 contracts.BaseAdapter)

### 启动流程统一
- CLI 和 Hermes 两条路径现在都使用 `launch_core()`
- 统一的 `LaunchRequest` 数据结构
- 9步统一流程确保一致性

### 端口默认值
- 所有端口默认值改为 5000 (符合 v1.1 契约)
- 浏览器打开 5000 而非 3333

## 零明文密钥检查

```bash
grep -rn "sk-" fleet/executors/ fleet/launcher/ fleet/notify/
```

结果: 无匹配 (通过)

## 交付物清单

| 文件 | 状态 | 说明 |
|------|------|------|
| `fleet/executors/base.py` | 重构 | 桥接到 contracts.py |
| `fleet/executors/fake.py` | 更新 | contracts-compatible |
| `fleet/executors/claudecode.py` | 更新 | contracts-compatible |
| `fleet/executors/codex.py` | 更新 | contracts-compatible |
| `fleet/executors/opencode.py` | 更新 | contracts-compatible |
| `fleet/executors/hermes.py` | 更新 | contracts-compatible |
| `fleet/executors/__init__.py` | 更新 | 导出新函数 |
| `fleet/launcher/launch_core.py` | 新建 | 统一启动核心 |
| `fleet/launcher/cli_start.py` | 重写 | 使用 launch_core |
| `fleet/launcher/hermes_entry.py` | 重写 | 修复解析器+mode |
| `fleet/launcher/__init__.py` | 更新 | 导出新函数 |
| `tests/int/test_resolve_chain.py` | 新建 | 9个测试用例 |
| `tests/test_fake.py` | 更新 | 使用 capabilities() |
| `tests/test_smoke.py` | 更新 | 使用 capabilities() |
| `tests/test_cli_launch.py` | 重写 | 使用 launch_core |
| `tests/core/test_resolve_integration.py` | 更新 | 移除 xfail |

## 结论

INT-03 已完成，所有6个原始缺陷已修复:
1. ✅ 控制台脚本路径 → `python -m fleet.console.server`
2. ✅ projects.json 双写 → 只写 SQLite
3. ✅ 浏览器端口 3333 → 5000
4. ✅ allowed_roots 硬编码 → 从 .env 读取
5. ✅ 端口默认值 3333 → 5000
6. ✅ 解析器空行截断 → 逐行状态机
7. ✅ mode 白名单增加 plan

BaseAdapter 桥接层已建立，resolve() 链路端到端通过，所有测试通过。
