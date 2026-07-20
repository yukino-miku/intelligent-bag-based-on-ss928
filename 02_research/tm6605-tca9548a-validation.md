# TCA9548A / TM6605 / 灯光验证状态

Rev2 使用 I2C0 的 TCA9548A `0x70`：CH0 BMI270 `0x68`，CH1 左 TM6605 `0x2d`，CH2 右 TM6605 `0x2d`。所有进程共享 `/run/lock/smartbag-i2c0-mux.lock`，事务顺序固定为加锁、选通道、选从地址、完整读写、释放锁。TM6605 的 effect `0x04` 与 play `0x0c` 在同一事务内完成。

自动测试覆盖通道选择、同址隔离、线程/进程锁、异常释放、非法通道、direct-I2C、BMI 与 haptic 并发，以及左右独立效果队列。BMI270 的 `--hardware-profile` 会在 Rev2 选择 CH0，在 legacy profile 恢复 direct-I2C。PWM 灯光测试覆盖 chip 发现、export 等待、disable/duty=0/period/duty/enable 顺序和 EINVAL 诊断文本。

当前证据等级：软件为 `UNIT TESTED`；真实 BMI270、左右 LRA 和左右灯均为 `BLOCKED`。只有操作员观察到对应侧实物响应，并保存 `i2c-events.csv`、`haptic-events.csv`、`light-events.csv`、errno 和 pinmux readback 后，才能写 `PHYSICALLY VERIFIED`。执行物理输出前必须确认独立供电、共地、电压和逻辑电平。
