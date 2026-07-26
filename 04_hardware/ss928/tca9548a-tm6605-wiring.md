# TCA9548A、BMI270 与 TM6605

| 上游/通道 | 下游设备 | 地址 | 用途 |
|---|---|---:|---|
| SS928 I2C0 | TCA9548A | `0x70` | I2C 通道选择 |
| TCA channel 0 | BMI270 | `0x68` | 姿态与跌倒采样 |
| TCA channel 1 | 左 TM6605 | `0x5A` | 左 LRA 震动 |
| TCA channel 2 | 右 TM6605 | `0x5A` | 右 LRA 震动 |

SS928 Pin3 接 TCA SDA，Pin5 接 TCA SCL。TCA 下游各通道的 SDA/SCL 分别连接对应模块。所有模块共地；电源电压和上拉必须按实物模块确认，不能仅根据芯片典型值接线。

BMI270 和告警控制器可能是两个进程，因此只锁 Python 线程不够。正式实现使用 `/run/lock/smartbag-i2c0-mux.lock`，把“选择 TCA 通道”和“下游 I2C 读写”放在同一临界区，避免串到错误设备。
