# SS928 Rev2 引脚入口

Rev2 接线、profile 差异、pinmux、供电和共地约束统一见 [ss928/40pin-usage.md](ss928/40pin-usage.md)。本文只作为 Rev2 文档入口，避免维护第二份会漂移的引脚表。

配置文件：`09_deliverables/board_deploy/hardware-profiles/rev2_tm6605_mr20.json`。切换前必须停止服务并清除全部输出，使用 `smartbag-hardware-profile.sh set rev2_tm6605_mr20` 完成备份、校验和失败回滚。
