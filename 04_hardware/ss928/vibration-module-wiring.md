# 震动与提示灯接线

正式 Rev2 震动链路为 `I2C0 -> TCA9548A -> 左/右 TM6605 -> 左/右 LRA`。TCA 通道和地址见 [40pin-usage.md](40pin-usage.md)，详细连接见 [tca9548a-tm6605-wiring.md](tca9548a-tm6605-wiring.md)。

Pin7/PWM10 驱动左提示灯，Pin32/PWM1 驱动右提示灯。两路 PWM 只接灯驱动模块控制输入，不能直接给灯供电。等级 3/4 使用灯光提示；震动等级 1 到 4 由 TM6605 波形映射执行。

`pwm_legacy` 仅用于旧四路震动硬件回退，才会使用 Pin7/32/35/37。默认 `tm6605` profile 不使用 Pin35/Pin37。启动、事件超时、detector 退出、SIGTERM 和异常退出均必须执行 `safe-off`。
