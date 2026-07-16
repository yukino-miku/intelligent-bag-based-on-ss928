# 硬件资源需求

| 资源 | 用途 | 约束 |
|---|---|---|
| 两个 USB 3.0/UVC 设备 | 左后、右后视觉输入 | 使用不同真实设备和独立稳定路径；优先分布到不同 USB 根控制器；preflight 并发读取首帧 |
| sensor0 MIPI + I2C7 | IMX347 可选诊断 | EULER_4SEN V1.0、2 lane；不属于默认双 USB 启动链 |
| I2C0 Pin3/5 | BMI270 | 3.3V，地址 0x68/0x69，IIO 或 userspace 二选一 |
| UART4 Pin8/10 | DX-GP21 | `/dev/ttyAMA4`，TTL 电平，NMEA 波特率与模块一致 |
| PWM Pin7/32/35/37 | 四路震动 | 独立电机驱动和电源，共地，启动/退出强制关闭 |
| I2S Pin12/38/40 | MAX98357 | 可选；不使用 MCLK，不占 Pin7 |
| Bluetooth/BlueZ | 统一 NUS | 只允许一个默认 GATT 服务所有者 |
| Wi-Fi/LAN | 双路 snapshot/MJPEG 和状态 | 手机与板端双向可达；BLE 不传视频；正式小程序网络规则另行验收 |
| 存储 | 模型、轨迹、日志 | 模型按部署策略单独下发；轨迹放 `/var/lib/smartbag/tracks` |

完整引脚与 pinmux 以 `04_hardware/ss928/40pin-usage.md` 为唯一事实来源。
