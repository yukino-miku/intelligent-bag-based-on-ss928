# Board Runtime Common

这里放置板端进程共享的轻量协议代码，不引入 Redis、MQTT 等中间件。

- `event_protocol.py`：跨进程单行 JSONL 事件封装。
- `ble_protocol.py`：统一 NUS 命令路由，支持 `AL`、`GNSS`、`IMU`、`SYS`，并兼容旧命令。

默认只有 SmartBag Alert Controller 注册 Nordic UART Service。GNSS 与 BMI270 作为子模块运行时使用 `--no-ble`，通过 JSONL/命令管道接入统一服务。
