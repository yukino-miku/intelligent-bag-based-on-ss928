# 最终分支收敛记录

审计及执行日期：2026-07-30。开始候选 HEAD 为 `3dc04d8fd4f6bd5cbd40fb54d6b0cb4e0497d1ee`，开始时默认分支为 `agent/ss928-board-integration`。`merge-base`、`branch --contains` 和双向 `rev-list` 证明三个旧分支的必要历史均已进入最终候选，旧分支相对候选没有独有提交。

| branch | 删除前 tip SHA | unique commits | archive tag | PR | 结果 |
|---|---|---:|---|---|---|
| `agent/ss928-board-integration` | `06c6cfd1dc11a0f92c54ce8aad5252d554ececa5` | 0 | `archive/agent-ss928-board-integration-20260730` | #6 base | 已归档并删除 |
| `agent/full-sanda-integration` | `c3ef9c012543cdc02c708449572e8645b98dcf48` | 0 | `archive/agent-full-sanda-integration-20260730` | #6 head / #7 base | 已归档并删除 |
| `agent/radar-primary-vision-class-fusion` | `33665efb06d0eccd765e254685dce564010597e4` | 0 | `archive/agent-radar-primary-vision-class-fusion-20260730` | #7 head | 已归档并删除 |

## 执行结果

- 三个 annotated archive tag 均已推送，并逐一验证 peeled commit 与删除前 tip 完全一致。
- PR #6 和 #7 已注明内容进入 `main` 后关闭，没有开放 PR 依赖已删除分支。
- `main` 已设为 GitHub 默认分支；旧远程与本地 agent 分支均已删除。
- 分支删除时 `main` 为 `36ae2427ee05accdd30626a31ac7d12200a87096`。
- `git ls-remote --heads origin` 最终仅返回 `refs/heads/main`，远程分支数为 1。
- 最终不可变发布提交由 annotated tag `smartbag-v1.0.0-rc2` 指向；tag 在最终元数据提交和 CI 通过后创建。

附加审计事实：stash 为空、Git LFS 无对象；`git fsck --full` 没有不可达 commit。历史分支仍可通过 archive tag 和 Git 历史读取。
