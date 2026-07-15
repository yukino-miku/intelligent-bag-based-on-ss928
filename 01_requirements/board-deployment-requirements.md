# SS928 板端部署需求

## 运行环境

- SS928/Hi3403/SD3403 系列板卡，Ubuntu 22.04 用户空间，root 可访问摄像头、I2C、UART、PWM 和 I2S。
- Python 3.10 及以上；视觉 PC/CPU 路径需要 OpenCV、Ultralytics 及其运行时，板端服务只使用轻量标准库，BLE 需要 BlueZ、dbus-python 和 PyGObject。
- 视觉模型、标定文件和本地配置由部署阶段提供，不提交权重、`.om`、设备 IP 或密码。
- 数据目录统一为 `/var/lib/smartbag`，日志由 systemd journal 管理，必要文件写入 `/var/log/smartbag`。

## 功能和性能

- 单摄是默认模式，依据地面横向坐标路由 left/right/both；双摄为兼容模式，不默认启动两个 YOLO 进程。
- detector 只把多帧稳定后的 `haptic_level` 写入 `vision_alert` JSONL，不允许 raw risk 直接驱动电机。
- 同侧同等级事件限流；等级降低、风险消失、detector 退出、超时、异常和进程终止均必须清零 PWM。
- 从稳定风险形成到 controller 接收事件的进程间目标时延小于 100 ms；视觉总时延由实际 CPU/NPU 后端另行验收。
- `board_cpu` 是 CPU 基线，不代表 SS928 NPU；真实 `.om` 后端完成前不得宣称 NPU 加速可用。

## 外设和服务

- 摄像头：默认 `/dev/video0`，支持 USB V4L2；IMX347 MIPI 需匹配当前 MPP/sensor 驱动。
- I2C0：BMI270，地址 `0x68`/`0x69`；支持 IIO 和用户态 I2C。
- UART4：DX-GP21，`/dev/ttyAMA4`，NMEA。
- PWM sysfs：四路左右震动，等级 0 到 4。
- I2S：MAX98357 可选音频，默认关闭且不得阻塞震动。
- 默认只能由 board service/controller 注册一个 Nordic UART Service，广播名 `SS928-SmartBag`；GNSS 和 BMI270 默认 `--no-ble`。
