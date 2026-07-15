# 部署流程

1. 在 PC 克隆仓库，单独准备模型和合法的 BMI270 配置 blob。
2. 在板端确认 Ubuntu、Python、BlueZ、摄像头、I2C0、UART4、PWM、I2S 和存储空间。
3. 运行 `09_deliverables/board_deploy/preflight.sh`。
4. 运行 `install.sh <仓库根目录>`，生成 `/etc/smartbag/config.json` 并安装 systemd units。
5. 先以 dry-run/simulate 验证，再启动 `smartbag.target`。
6. 使用 `status.sh`、`logs.sh` 和统一 BLE 的 `SYS STATUS` 检查。
7. 真实硬件验收必须覆盖 detector 退出清振、事件超时、左右路由、摄像头首帧、GNSS checksum、BMI 姿态和 BLE 唯一服务。
