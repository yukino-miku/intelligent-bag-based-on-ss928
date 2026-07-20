# SS928 板端部署需求

## 运行环境

- SS928/Hi3403/SD3403 系列板卡，目标 Ubuntu 22.04/aarch64 用户空间，root 可访问摄像头、I2C、UART、PWM 和 I2S；实际镜像版本必须用 `/etc/os-release` 验证。
- Python 3.10 及以上；视觉 PC/CPU 路径需要 OpenCV、Ultralytics 及其运行时，板端服务只使用轻量标准库，BLE 需要 BlueZ、dbus-python 和 PyGObject。
- 视觉模型、标定文件和本地配置由部署阶段提供，不提交权重、`.om`、设备 IP 或密码。
- 数据目录统一为 `/var/lib/smartbag`，日志由 systemd journal 管理，必要文件写入 `/var/log/smartbag`。

## 功能和性能

- 双 USB 摄像头是默认模式：左右 detector 固定物理 side，分别维护 tracker、风险状态和标定；单摄 auto 仅保留兼容测试。
- 每个摄像头只能由对应 detector 打开一次；采集、推理和视频预览使用有界 latest-frame buffer，不允许旧帧无限积压。
- detector 只把多帧稳定后的 `haptic_level` 写入 `vision_alert` JSONL，不允许 raw risk 直接驱动电机。
- 同侧同等级事件限流；等级降低、风险消失、detector 退出、超时、异常和进程终止均必须清零 PWM。
- 从稳定风险形成到 controller 接收事件的进程间目标时延小于 100 ms；视觉总时延由实际 CPU/NPU 后端另行验收。
- `board_cpu` 是 CPU 基线，不代表 SS928 NPU；真实 `.om` 后端完成前不得宣称 NPU 加速可用。
- 视频通过可互访的 Wi-Fi/LAN snapshot/MJPEG 传输，BLE 只承载告警、状态和命令；真实双路 FPS、USB 带宽、CPU、内存和温度必须上板验收。

## 外设和服务

- 摄像头：两个不同的 USB V4L2 设备；序列号唯一时可用 `/dev/v4l/by-id`，相同型号/序列号时必须固定物理口并用两个不同的 by-path。默认配置不得使用同一真实节点，双路还必须通过并发首帧测试。IMX347 MIPI 只作可选诊断，不进入默认服务。
- Rev2 I2C0：TCA9548A `0x70`；CH0 BMI270 `0x68`，CH1/CH2 左右 TM6605 `0x2d`。每笔事务必须持有 `/run/lock/smartbag-i2c0-mux.lock` 并重新选通道。Legacy 可直接访问 BMI270。
- UART4：DX-GP21，`/dev/ttyAMA4`，NMEA。
- Rev2 PWM sysfs：Pin7/Pin32 仅用于左右灯光；振动改为 TM6605/LRA。Legacy 才使用四路 PWM 振动，两个 profile 不得并行。
- MR20：默认右后雷达 `192.168.1.200:2369`，板端 `eth1` `192.168.1.102:2368`，只允许 `/32` host route，不得修改 eth0、默认路由或网关。
- I2S：MAX98357 可选音频，默认关闭且不得阻塞震动。
- 默认只能由 board service/controller 注册一个 Nordic UART Service，广播名 `SS928-SmartBag`；GNSS 和 BMI270 默认 `--no-ble`。
- Cloud telemetry 是可选独立服务，必须 HTTPS、HMAC、timestamp、nonce、body SHA256、有界离线队列和用户设备绑定；断网/云故障不得阻塞视觉、雷达、BLE 或执行器。
