# 最终分支收敛计划

审计日期：2026-07-30。开始时远程默认分支为 `agent/ss928-board-integration`，候选分支远程实际 HEAD 为 `3dc04d8fd4f6bd5cbd40fb54d6b0cb4e0497d1ee`。`git merge-base --is-ancestor` 和 `git rev-list HEAD..<branch>` 证明三个远程分支头均已包含在候选历史中，旧分支相对候选没有独有提交。

| branch | tip SHA | 已包含 | unique commits | archive tag | PR | 最终处理 |
|---|---|---:|---:|---|---|---|
| `agent/ss928-board-integration` | `06c6cfd1dc11a0f92c54ce8aad5252d554ececa5` | 是 | 0 | `archive/agent-ss928-board-integration-20260730` | #6 base | 归档后删除 |
| `agent/full-sanda-integration` | `c3ef9c012543cdc02c708449572e8645b98dcf48` | 是 | 0 | `archive/agent-full-sanda-integration-20260730` | #6 head / #7 base | 归档后删除 |
| `agent/radar-primary-vision-class-fusion` | 最终发布提交 | 是 | 0 | `archive/agent-radar-primary-vision-class-fusion-20260730` | #7 head | 发布 main 后归档并删除 |

执行顺序：

1. 在删除前按准确分支 tip 创建并推送三个 annotated archive tag。
2. 再次 fetch/prune，并复查 `merge-base`、双向 `rev-list` 和开放 PR。
3. 将最终候选 HEAD 创建为 `main`；保留完整祖先历史。
4. 等待 main CI 通过，创建 `smartbag-v1.0.0-rc2` tag 与 GitHub prerelease。
5. PR #6/#7 以“已完整整合到 main”说明关闭，不能继续依赖待删分支。
6. 把 GitHub 默认分支改为 `main`，删除三个远程 agent 分支，再清理对应本地分支。
7. 最终 `git ls-remote --heads origin` 必须只返回 `refs/heads/main`。

审计附加事实：stash 为空、Git LFS 无对象、`git fsck --full` 只有不可达 blob，无不可达 commit；现有 tag/Release 为 `smartbag-v1.0.0-rc1`。最终 main/rc2 SHA 和 deletion status 在发布提交后回填 JSON 与发布清单。
