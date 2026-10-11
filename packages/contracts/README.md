# packages/contracts —— AideanFleet 契约唯一源（规划稿，待 TASK-001 落库）

- 唯一源形式：**JSON Schema（draft 2020-12 子集）**，本目录即唯一源。
  Python 侧 TypedDict / 前端 `fleet/console/web/src/api/types.ts` 必须由 `contracts-gen` 生成，禁止手写第二份。
- 为什么不选 OpenAPI/pydantic：仓库 AGENTS.md §六-4 禁止可避免依赖；FastAPI 自带的 /openapi.json 是**实现导出物**，
  只用于契约测试比对，不作为源（见 ADR-002）。
- 子集约束（便于零依赖校验器实现）：type / properties / required / enum / items / additionalProperties:false /
  minLength / maxLength / minimum / pattern / $ref（仅本目录内相对引用）/ oneOf（仅判别字段）。
- 统一口径：
  - 字段名 snake_case；时间 = ISO 8601 UTC 带 `Z`（如 `2026-10-11T10:20:11Z`）；
  - ID：goal `G-<毫秒时间戳hex>-<seq>`、todo `T-<毫秒时间戳hex>-<seq>`（已确认：fleet/kernel/kernel.py:95,102）；setup 作业 `J-<毫秒时间戳hex>-<seq>`（新增）；
  - 无金额字段；额度为整数“次”。
  - 所有响应外层：成功 `{"ok": true, ...}`，失败见 errors.json `ErrorBody`（与 server.py 现有 `{"ok":false,"error":...,"reason":...}` 兼容）。

| 文件 | 契约 |
|---|---|
| api.json | ① API：路径/方法/请求/响应/分页/幂等/鉴权 |
| errors.json | ② Errors：错误码枚举、HTTP 映射、错误体、前端展示 |
| identity.json | ③ Identity：主体、角色、会话、管理面边界 |
| resources.json | ④ Resources：证据/日志/运行时文件的路径规则与访问控制 |
| events.json | ⑤ Events：kernel 事件名、载荷、触发时机、幂等键 |
| ux-states.json | ⑥ UX States：核心界面五态 |
| schemas/*.json | 共享 DTO |
