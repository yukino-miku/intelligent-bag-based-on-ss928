# SS928 40Pin 资源分配（唯一事实来源）

本文是本项目 40Pin 接线和 pinmux 的唯一事实来源。其他文档只引用本表，不重复定义冲突引脚。修改接线前必须同时检查 pinmux、设备树和 `/sys/class/pwm` 实际编号。

| Pin | 信号 | 用途 | Linux 接口 | pinmux |
|---:|---|---|---|---|
| 3 | I2C0_SDA | BMI270 SDA | `/dev/i2c-0` | `bspmm 0x102F013c 0x2031` |
| 5 | I2C0_SCL | BMI270 SCL | `/dev/i2c-0` | `bspmm 0x102F0140 0x2031` |
| 7 | PWM0_OUT10_0_P | 左侧震动 1 | `pwmchip0/pwm10` | `bspmm 0x102F0110 0x1205` |
| 8 | UART4_TXD | DX-GP21 RX | `/dev/ttyAMA4` | `bspmm 0x102F0138 0x1201` |
| 10 | UART4_RXD | DX-GP21 TX | `/dev/ttyAMA4` | `bspmm 0x102F0134 0x1201` |
| 12 | I2S_BCLK | MAX98357 BCLK | AUDIO/I2S | `bspmm 0x102F010C 0x1202` |
| 32 | PWM0_OUT1_0_P | 左侧震动 2 | `pwmchip0/pwm1` | `bspmm 0x102F01EC 0x1201` |
| 35 | PWM0_OUT14_0_P | 右侧震动 1 | `pwmchip0/pwm14` | `bspmm 0x102F0100 0x1205` |
| 37 | PWM0_OUT15_0_P | 右侧震动 2 | `pwmchip0/pwm15` | `bspmm 0x102F00DC 0x1205` |
| 38 | I2S_WS | MAX98357 LRC/WS | AUDIO/I2S | `bspmm 0x102F0108 0x1102` |
| 40 | I2S_SD_TX | MAX98357 DIN | AUDIO/I2S | `bspmm 0x102F0104 0x1202` |

供电约束：BMI270 使用 3.3V；传感器、GNSS、功放控制侧和震动驱动控制侧必须与板卡共地；电机与功放不得直接由 GPIO 供电。MAX98357 不需要 MCLK，因此 Pin7 保留给 PWM，不作为 I2S MCLK。

当前表内未发现复用冲突。IMX347 使用板载 sensor0 MIPI/I2C7，不占用上述扩展口 I2C0、UART4、PWM 和 I2S 引脚。
