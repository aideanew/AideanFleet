# S5 验收：真实执行体端到端与降级可视化（TASK-501）

> 状态：**blocked（U-05）**——需要 codex（配模型池 key）与 claude（自身凭据）均已安装登录。
> 自动化入口：`FLEET_REAL_HARNESSES=1 python -m pytest tests/e2e/test_real_harness.py -q`
> （无凭据环境整文件 skip，不 fail。）

## 人工演示步骤

1. `fleet setup install codex claude`（或 /setup 一键安装）+ 分别完成登录。
2. `fleet.toml` 配置：
   ```toml
   [models.agnes]
   base_url = "https://apihub.agnes-ai.com/v1"
   model_id = "agnes-3.0-flash"
   api_key_env = "AGNES_API_KEY"

   [roles.fe-1]
   harness = ["codex", "claude"]
   models = ["agnes"]
   ```
3. 控制台 /tasks/new 提交小需求 → 看板观察：plan todo 出计划 → exec todo 由 codex 执行
   （attempt.harness=codex，model=agnes 桥接）→ verify → done。
4. 重命名 codex 可执行文件（模拟卸载）→ 再提一个需求 → 任务由 claude 完成（宿主自身凭据）。
5. 再把 claude 也移走 → 任务 blocked，attention 显示原因（执行体链全部不可用）。

## 验收标准

- [ ] codex 与 claude 各完成 ≥1 个 exec todo（attempt 表可见两种 harness）
- [ ] 模拟卸载后任务自动降级到另一个执行体；全不可用时 blocked 且 note 含原因
- [ ] 执行体页（/executors）标红未就绪项并可『去登录』
- [ ] 无凭据环境中测试 skip 而非 fail
