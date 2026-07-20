# MR20 集成状态

## 接口

- 雷达：`192.168.1.200:2369`；板端：`192.168.1.102:2368`；接口：`eth1`。
- 网络只使用 `192.168.1.102/32` 和到 `192.168.1.200/32 dev eth1 scope link` 的 host route，不设置网关、默认路由，不修改 eth0。
- 运行时支持 14 字节帧、0x60A 列表状态、0x60B 目标、未知帧计数、来源 IP/端口检查、scan 聚合、目标距离/速度/TTC、固定 side 和多帧确认。

## 证据状态

| 项目 | 状态 | 证据 |
|---|---|---|
| 帧解析、未知帧和来源过滤 | UNIT TESTED | `mr20_radar/tests/test_mr20_radar.py` |
| 0x60A/0x60B 连续 scan | REPLAY TESTED | 匿名化 `official-example.hex` |
| eth1、host route、ping、UDP bind | BLOCKED | 需当前 Rev2 板端网络日志 |
| 真实 0x60B 移动目标 | BLOCKED | 需 `mr20-capture.sh` 原始帧和目标动作说明 |
| 雷达风险到 TM6605/灯/BLE | BLOCKED | 需 controller session 的 source/effective/actuator 时间戳 |

上游历史只证明过物理链路、ping、UDP 和部分 0x60A/0x201/0x700 帧，不能据此宣称目标避障可用。板端先运行 `mr20-network-preflight.sh`，再在停止 controller 后用 `mr20-capture.sh --output <session>/radar-frames.csv` 采集；确认含 0x60B 后再启动 controller 做闭环。
