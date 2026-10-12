# AideanFleet Windows 安装器（S2 / TASK-201 / ADR-003）

## 产物

`AideanFleet-Setup-<ver>-UNSIGNED.exe`（CI 签名后为 `AideanFleet-Setup-<ver>.exe`）。

按用户安装（`PrivilegesRequired=lowest`）到 `%LOCALAPPDATA%\Programs\AideanFleet`：
- `runtime/python/`、`runtime/node/`：私有运行时（构建期离线内置，用户机器不联网装运行时，A-14）
- `wheelhouse/`：AideanFleet wheel + 依赖 wheel，`pip --no-index` 离线安装
- `fleet/console/dist/`：控制台前端（无 Node 也有 UI）
- `launcher.cmd`：快捷方式目标 = 私有 python 跑 `fleet up --open`（未就绪进 /setup，就绪进 /tasks）
- 桌面 + 开始菜单快捷方式；控制面板可卸载；默认保留 `%LOCALAPPDATA%\AideanFleet\data`

## 构建步骤（CI = .github/workflows/installer.yml）

```powershell
python scripts/installer/windows/fetch_runtimes.py            # 下载 Python embeddable + Node zip 并校验 SHA256
python -m pip install build && python -m build --wheel        # 产物 wheel
python -m pip download -q -d scripts/installer/windows/_wheelhouse .   # 依赖 wheelhouse
cd fleet/console/web && npm ci && npm run build               # 前端 dist
iscc scripts/installer/windows/AideanFleet.iss                # 产出 exe（需 Inno Setup 6 + 中文语言包）
```

## manifest.json

组件清单唯一源（DESIGN-001）：`name · kind · min_version · detect · install(type/package) · urls.official / urls.cn · sha256（zip 类）· default`。
CLI 安装走 `/setup`（fleet.setup 用私有 npm）；`grok` 为 official_script，默认不装（A-10）。

## 安全口径

- 运行时 zip 的 SHA256 在构建期校验（fetch_runtimes.py），不一致即中止构建。
- official_script 类（grok）不代跑远程脚本——向导展示官方 URL，由用户手动执行（MN-02/供应链）。
- exe 由 TASK-207 流水线签名；无证书时产物名带 `-UNSIGNED`，release job 拒绝发布未签名包。
