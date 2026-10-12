# S4 验收：Claude Code 宿主内 /fleet 跑通一个 todo（TASK-402）

> 状态：**blocked（U-05）**——需要一台已安装并登录 Claude Code 的机器。
> TASK-401 已交付自动化覆盖（`tests/kernel/test_cli_and_gates.py` 的
> next→running / writeback 机器门 / B4 校验），本卡是真实宿主的人工演示脚本。

## 步骤

1. `fleet skills install --host claude`（写入 ~/.claude/skills/fleet/SKILL.md）。
2. 建一个目标（任选其一）：
   - `python -m fleet.cli.main` 无该入口时用控制台 /tasks/new；
   - 或直接调 API：`POST /api/kernel/goals`（title/description/workspace）。
   目标包含 1 个 exec todo，verify=`python -m pytest -q`（在示例仓 cwd 下执行）。
3. 在 Claude Code 会话内执行 `/fleet 完成 <todo 标题>`。
4. 宿主按 skill 指引：`fleet next --agent claude --json` 认领 → 修改 → `fleet writeback --todo <id> --agent claude --verdict done`。
5. 录屏保留全过程；随后核对：

```bash
python - <<'PY'
from fleet.kernel import Kernel
from fleet.core.paths import paths
k = Kernel(paths().data_dir / "kernel.db")
todo = [t for t in k.todos() if t["claimed_by"] == "claude"][-1]
assert todo["status"] == "done", todo["status"]
attempts = k.attempts_of(todo["id"])
assert attempts[-1]["harness"] == "host"
events = [e["kind"] for e in k.pending_events(100)]
chain = [e["kind"] for e in events]
assert chain.index("todo:claimed") < chain.index("todo:running") < chain.index("todo:verifying") < chain.index("todo:done")
print("OK", todo["id"])
PY
```

## 验收标准（对照任务卡）

- [ ] todo 状态 done，attempt.harness=host
- [ ] events 中 claimed→running→verifying→done 顺序完整
- [ ] 无人工改库操作（全程只经 fleet CLI）
