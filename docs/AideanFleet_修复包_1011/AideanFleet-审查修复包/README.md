# AideanFleet 审查修复包（基于 origin/main 6c40830）

内容：
- `audit-6c40830.md` —— 完整审查报告（声明核验、测试计数、缺陷清单、设计审查）
- `AideanFleet-fixes.bundle` —— 11 个修复提交的 git bundle（origin/main..audit/verify-6c40830，HEAD = 0b97ba4）
- `AideanFleet-fixes-patches/` —— 同样 11 个提交的补丁序列（0001–0011）

以下两种方式任选其一。**本包未推送任何内容**，推送由你决定。

## 方式 A：拉取 bundle（推荐，提交哈希与审查分支完全一致）

```bash
cd AideanFleet
git fetch origin
git checkout -B audit/verify-6c40830 origin/main      # origin/main 必须仍是 6c40830
git bundle verify /path/to/AideanFleet-fixes.bundle
git pull --ff-only /path/to/AideanFleet-fixes.bundle audit/verify-6c40830
git log --oneline origin/main..HEAD                   # 应看到 11 个 [fix] 提交
```

## 方式 B：应用补丁

```bash
cd AideanFleet
git fetch origin
git checkout -B audit/verify-6c40830 origin/main
git am --keep-cr /path/to/AideanFleet-fixes-patches/*.patch   # 仓库有 CRLF 文件，必须加 --keep-cr
```

## 推送（用你的 GitHub PAT；不要把 PAT 写进任何文件或提交）

```bash
# 推到同名分支后在 GitHub 开 PR（推荐）
git push https://<你的GitHub用户名>:<PAT>@github.com/aideanew/AideanFleet.git audit/verify-6c40830

# 或者已配置凭据助手时：
git push origin audit/verify-6c40830
```

推送前建议本地再跑一次：

```bash
make setup && make guard          # Windows：.\make.ps1 guard
cd fleet/console/web && npx vue-tsc --noEmit
```

注意：如果 origin/main 已经不是 6c40830，方式 A 的 `--ff-only` 会失败，改用 `git rebase` 或方式 B。
