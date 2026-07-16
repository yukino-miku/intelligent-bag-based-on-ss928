# 部署流程

1. 在 PC 克隆仓库，单独准备模型和合法的 BMI270 配置 blob。
2. 在板端确认 Ubuntu/aarch64、Python、BlueZ、两路 UVC、USB 拓扑、I2C0、UART4、PWM、I2S 和存储空间。
3. 用稳定 by-id 固定左右设备；若相机序列号相同，则固定物理 USB 口并使用两个不同的 by-path。分别标定并生成 `/etc/smartbag/calibration-left.json` 与 `calibration-right.json`。
4. 运行 `09_deliverables/board_deploy/check-runtime-deps.sh` 和 `preflight.sh /etc/smartbag/config.json`；preflight 会并发读取两路首帧。
5. 运行 `install.sh <仓库根目录>`，生成 `/etc/smartbag/config.json` 并安装 systemd units。
6. 先用 `dual-vision-test.sh left.mp4 right.mp4` 验证模拟双路，再启动 `smartbag.target`。
7. 使用 `status.sh`、`logs.sh`、HTTP `/api/v1/status` 和统一 BLE 的 `SYS STATUS` 检查。
8. 真实硬件验收必须覆盖 detector 退出只清本侧、事件超时、固定左右路由、双摄持续帧率/温度、GNSS checksum、BMI 姿态、BLE 唯一服务和手机真机 snapshot。
