# SS928 40Pin 资源分配（唯一事实来源）

本文是项目接线和 pinmux 的唯一事实来源。运行时必须显式选择 `rev2_tm6605_mr20` 或 `legacy_pwm_haptics`；两种 profile 不得同时驱动。

| Pin | 信号 | Rev2 用途 | Legacy 用途 | Linux/pinmux |
|---:|---|---|---|---|
| 3 | I2C0_SDA | TCA9548A 主端 SDA | BMI270 SDA | `/dev/i2c-0`; `bspmm 0x102F013c 0x2031` |
| 5 | I2C0_SCL | TCA9548A 主端 SCL | BMI270 SCL | `/dev/i2c-0`; `bspmm 0x102F0140 0x2031` |
| 7 | PWM0_OUT10_0_P | 左灯 PWM | 左震动 1 | PWM channel 10; `bspmm 0x102F0110 0x1205` |
| 8 | UART4_TXD | DX-GP21 RX | 同左 | `/dev/ttyAMA4`; `bspmm 0x102F0138 0x1201` |
| 10 | UART4_RXD | DX-GP21 TX | 同左 | `/dev/ttyAMA4`; `bspmm 0x102F0134 0x1201` |
| 12 | I2S_BCLK | MAX98357 BCLK | 同左 | `bspmm 0x102F010C 0x1202` |
| 32 | PWM0_OUT1_0_P | 右灯 PWM | 左震动 2 | PWM channel 1; `bspmm 0x102F01EC 0x1201` |
| 35 | PWM0_OUT14_0_P | 未使用 | 右震动 1 | PWM channel 14; `bspmm 0x102F0100 0x1205` |
| 37 | PWM0_OUT15_0_P | 未使用 | 右震动 2 | PWM channel 15; `bspmm 0x102F00DC 0x1205` |
| 38 | I2S_WS | MAX98357 LRC/WS | 同左 | `bspmm 0x102F0108 0x1102` |
| 40 | I2S_SD_TX | MAX98357 DIN | 同左 | `bspmm 0x102F0104 0x1202` |

Rev2 的 I2C 分支固定为：TCA9548A `0x70`，CH0 BMI270 `0x68`，CH1 左 TM6605 `0x2d`，CH2 右 TM6605 `0x2d`。每笔事务都必须重新选通道并持有 `/run/lock/smartbag-i2c0-mux.lock`。

MAX98357 不需要 MCLK，Pin7 不得作为音频 MCLK。LRA 不得直连 GPIO；灯光负载不得由 GPIO/PWM 引脚供电。TM6605、灯光驱动和电机/灯负载使用符合模块规格的独立电源，并与 SS928 共地；电压、电流和逻辑电平仍需按实物资料确认。

`pwmchip` 编号可能随内核变化。profile 中的 chip/channel 是当前候选值，必须用 `pwm-list.sh` 和 `pwm-probe.py` 在板端确认后才能标记实物通过。IMX347 使用 sensor0 MIPI/I2C7，不占用表内扩展口。
