# SS928 Rev2 硬件刷新最新摘要

日期：2026-07-20。代码分支：`agent/sanda-hardware-refresh`。来源：`sanda-tt/ss928@970351c84a12f3219e7910ee488ac5ff579d6f98`。

| 项目 | 状态 | 当前证据 |
|---|---|---|
| 上游差异和许可审计 | IMPLEMENTED | import manifest + GitHub API 固定 SHA |
| TCA9548A/I2C 并发 | UNIT TESTED | mock 事务、锁、异常、direct-I2C |
| TM6605/LRA | UNIT TESTED | effect/play 原子事务和左右调度；无实物响应 |
| 双侧灯光 | UNIT TESTED | sysfs mock 和 EINVAL 路径；无实物响应 |
| MR20 | REPLAY TESTED | 0x60A/0x60B 匿名帧；无当前板端 0x60B |
| vision/radar/manual 融合 | UNIT TESTED | max-by-side、来源 clear/timeout/exit 隔离 |
| CloudBase | IMPLEMENTED + UNIT TESTED | 本地 HMAC/queue/JS；NOT DEPLOYED |
| 30 分钟联合运行 | BLOCKED | 需要 Rev2 实物和板端依赖 |
| 本地 Python 回归 | UNIT TESTED | 267 项通过；Windows 上 1 项 Linux `fcntl` 进程锁测试跳过 |
| 小程序/Cloud JS | UNIT TESTED | 6 个测试文件通过，24 个 JS 文件通过语法检查 |
| 配置与部署静态检查 | UNIT TESTED | JSON、CI YAML、shell `sh -n`、profile migration、仓库策略、whitespace 通过 |
| 当前 SS928 连接 | BLOCKED | Windows 未枚举 USB 串口/USB 网卡，`192.168.1.168:22` 不可达 |

本文件只记录已获得证据。当前没有将 mock/replay 写成板端实物通过。真实 session 应保存到被 Git 忽略的 `08_media/hardware_refresh_runs/<SESSION_ID>/`，仓库只更新匿名摘要。重新连接 USB-UART 或 USB gadget 后，先运行只读 `full-hardware-test.sh`；左右 LRA/灯光仍必须由操作员确认供电和接线后分别显式执行物理测试。
