# TCA9548A / TM6605 / 灯光验证状态

Rev2 使用 I2C0 的 TCA9548A `0x70`：CH0 BMI270 `0x68`，CH1 左 TM6605 `0x2d`，CH2 右 TM6605 `0x2d`。所有进程共享 `/run/lock/smartbag-i2c0-mux.lock`，事务顺序固定为加锁、选通道、选从地址、完整读写、释放锁。当前目标仓库、`10_archive` 文件名/正文索引和已迁移队友代码中，可追溯确认的 TM6605 接口只有地址 `0x2d`、effect 寄存器 `0x04`、play/stop 寄存器 `0x0c`，以及 effect 15/14 的既有用法；没有找到足以确认线性 gain/amplitude 寄存器的可分发数据手册。因此实现没有编造增益寄存器，而是用 effect 15/14 和 1800/1000/600/300 ms 重复周期形成四档可区分触觉模式。它不是经过仪器验证的线性振幅四档。

自动测试覆盖通道选择、同址隔离、线程/进程锁、异常释放、非法通道、direct-I2C、BMI 与 haptic 并发，以及左右独立有界状态机。每侧只保存 requested/applied level、effect、next play、cycle、active、play/error count；同级 heartbeat 不创建队列，等级切换先 stop 再立即启动新模式。BMI270 的 `--hardware-profile` 会在 Rev2 选择 CH0，在 legacy profile 恢复 direct-I2C。PWM 灯光同样只保存当前 phase 和 next transition，Level 3 持续 1000/1000 ms 慢闪，Level 4 持续 200/200 ms 快闪。

当前证据等级：软件为 `UNIT TESTED`；按用户本轮最新要求未执行板端烧录和通电，真实 BMI270、左右 LRA 和左右灯均为 `NOT RUN`。未来即使 I2C 写成功也只能标 `ELECTRICALLY EXERCISED`；只有传感器证据或操作员确认对应侧实物响应，并保存完整 session、errno 和 pinmux readback 后，才能写 `PHYSICALLY VERIFIED`。执行物理输出前必须确认独立供电、共地、电压和逻辑电平。
