# S2 验收：干净 Windows 机器端到端安装演示（TASK-206）

> 状态：**blocked（U-07）**——需要一台无 Python/Node/Git 的干净 Windows 10/11 x64 虚拟机（标准用户账户）。
> 本文档是逐步可复制的人工验收脚本；exe 来自 `.github/workflows/installer.yml` 的 artifact
> `aideanfleet-installer`（未拿到签名证书 U-12 前为 `-UNSIGNED` 内部测试包）。

## 前置

- [ ] 干净 Windows 10/11 x64 VM 快照（无 Python/Node/Git，标准用户，非管理员）
- [ ] 可访问 GitHub Actions 下载 artifact（内网/代理均可）
- [ ] 计时器 + 截图/录屏工具

## 步骤

### 1. 首次安装与启动（指标 M1 首测）

1. 下载 `AideanFleet-Setup-<ver>.exe`（或 `-UNSIGNED`），**双击安装并开始计时**：
   `powershell -Command "Get-Date -Format o" | Tee-Object m1-start.txt`
2. 记录 SmartScreen 提示：签名版应显示发布者名称；UNSIGNED 版记录为预期警告（截图）。
3. 安装器完成后勾选「立即启动」→ 浏览器自动打开。
4. 浏览器出现 `/setup` 组件页的时刻记为终点：
   `powershell -Command "Get-Date -Format o" | Tee-Object m1-end.txt`
5. **M1 = end − start**（无基线前不设阈值；结果填入本文件末尾记录表）。

### 2. /setup 一键安装 CLI

- [ ] 组件页显示 python/node 为「已安装（私有副本）」；6 个 CLI 为「未安装」（grok 默认不装）。
- [ ] 点「一键安装缺失组件」→ 逐组件进度 → 全绿。
- [ ] 屏蔽 `registry.npmjs.org`（hosts 文件加 `127.0.0.1 registry.npmjs.org`）后，对任一失败组件点
      「切换国内镜像重试」→ 成功（REQ-NF-05）。测完移除 hosts 条目。
- [ ] 失败注入（可选）：对某组件断网重试 → 中文错误 + 「重试此项」可用。

### 3. 首次配置（S3 连测）

- [ ] 第 2 步填模型 base_url/model_id/key → 「保存并测试连通」→ reachable=true。
- [ ] 刷新页面：key 状态为「有 key」，且**任何界面都看不到密钥明文**（B2）。
- [ ] 第 3 步对任一已装 CLI 点「去登录」→ 本机新终端弹出官方登录流程（不代填任何凭据，MN-02）。
- [ ] 登录完成后徽章变绿 → ready=true → 「开始第一个任务」可进入 /tasks/new。

### 4. 一键启动与降级可视化

- [ ] 关闭浏览器与控制台 → 双击桌面「AideanFleet」快捷方式 → 自动打开 /tasks。
- [ ] 在 /tasks/new 提交一个小需求 → 看板出现计划任务 → 执行 → 验收 → 绿色「完成」。
- [ ] 重命名 `%LOCALAPPDATA%\Programs\AideanFleet\npm-global` 下某 CLI（模拟卸载）→
      执行体页该项标红「未安装」；任务自动降级或 blocked 且原因可见。

### 5. 卸载

- [ ] 控制面板卸载 → 安装目录消失、控制面板无残留项；
- [ ] `%LOCALAPPDATA%\AideanFleet\data` 默认保留；勾选「删除任务数据」时不保留。

## 安装前后系统完整性

```powershell
reg export HKLM\SOFTWARE before.hku /y ; reg export HKLM\SOFTWARE after.hku /y   # 对比无新增
[System.Environment]::GetEnvironmentVariable('Path','Machine')                    # 前后一致（MN-03）
```

## 记录表（验收时填写）

| 项 | 结果 |
| --- | --- |
| M1 双击 → /setup 全绿（分钟） | 未测（U-07） |
| SmartScreen 表现 | 未测 |
| npm 镜像回退 | 未测 |
| 密钥零明文（B2） | 未测 |
| 降级标红 | 未测 |
| 卸载干净 | 未测 |
