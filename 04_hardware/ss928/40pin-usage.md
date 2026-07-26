# SS928 40Pin 资源分配（唯一事实来源）

本表描述正式 `dual-usb-base`/Rev2 运行方案。其他文档只能引用本表；改线时必须同步核对 pinmux、设备树和板端实际设备节点。

| Pin | 信号 | 正式用途 | Linux 接口 | pinmux |
|---:|---|---|---|---|
| 3 | I2C0_SDA | TCA9548A SDA；下游 BMI270、左右 TM6605 | `/dev/i2c-0` | `bspmm 0x102F013c 0x2031` |
| 5 | I2C0_SCL | TCA9548A SCL | `/dev/i2c-0` | `bspmm 0x102F0140 0x2031` |
| 7 | PWM0_OUT10_0_P | 左侧提示灯 | `pwmchip0/pwm10` | `bspmm 0x102F0110 0x1205` |
| 8 | UART4_TXD | DX-GP21 RX（可选） | `/dev/ttyAMA4` | `bspmm 0x102F0138 0x1201` |
| 10 | UART4_RXD | DX-GP21 TX（可选） | `/dev/ttyAMA4` | `bspmm 0x102F0134 0x1201` |
| 12 | I2S_BCLK | MAX98357 BCLK（可选） | AUDIO/I2S | `bspmm 0x102F010C 0x1202` |
| 32 | PWM0_OUT1_0_P | 右侧提示灯 | `pwmchip0/pwm1` | `bspmm 0x102F01EC 0x1201` |
| 35 | PWM0_OUT14_0_P | 旧四路 PWM 回退预留；Rev2 默认不用 | `pwmchip0/pwm14` | 仅 `pwm_legacy` 配置 |
| 37 | PWM0_OUT15_0_P | 旧四路 PWM 回退预留；Rev2 默认不用 | `pwmchip0/pwm15` | 仅 `pwm_legacy` 配置 |
| 38 | I2S_WS | MAX98357 LRC/WS（可选） | AUDIO/I2S | `bspmm 0x102F0108 0x1102` |
| 40 | I2S_SD_TX | MAX98357 DIN（可选） | AUDIO/I2S | `bspmm 0x102F0104 0x1202` |

I2C0 正式分配：TCA9548A 地址 `0x70`；通道 0 为 BMI270 `0x68`，通道 1 为左 TM6605 `0x5A`，通道 2 为右 TM6605 `0x5A`。BMI270 与 TM6605 的通道选择和随后的传输必须持有同一把 `/run/lock/smartbag-i2c0-mux.lock` 跨进程锁。

MR20 通过独立以太网 UDP 端口接入，MT5710 通过 USB NCM/PCUI 接入，两者不占用 40Pin。两路 UVC 摄像头接 USB；正式方案固定左右设备，不采用交替采集。IMX347 示例使用 sensor0 MIPI/I2C7，不进入默认启动链。

所有模块控制侧与 SS928 共地。BMI270、TCA9548A 和 TM6605 的逻辑电平必须按实际模块规格核对，LRA、电机、灯和功放不得直接由 GPIO 供电。MAX98357 不需要 MCLK。
