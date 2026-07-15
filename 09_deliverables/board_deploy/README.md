# SS928 板端部署包

默认架构由 `smartbag-alert.service` 监督单摄视觉、GNSS 和 BMI270 子进程，并独占 `SS928-SmartBag` BLE NUS。独立 vision/GNSS/IMU unit 仅用于诊断，与默认服务互斥。

```sh
cd /path/to/intelligent-bag-based-on-ss928/09_deliverables/board_deploy
sudo sh preflight.sh
sudo sh install.sh /path/to/intelligent-bag-based-on-ss928
sudo install -m 0644 /path/to/yolo11n.pt /root/smartbag/models/yolo11n.pt
sudo sh start-all.sh
sh status.sh
sh logs.sh -f
```

停止和卸载：

```sh
sudo sh stop-all.sh
sudo sh uninstall.sh
```

安装不会删除 `/etc/smartbag` 与 `/var/lib/smartbag`。BMI270 用户态 I2C 模式还需按合法来源提供 config blob；没有 blob 时优先使用内核 IIO。音频默认关闭，只有提供一套合法的 L1..L4/R1..R4 AAC 并在配置中启用后才播放。

双摄不由默认 unit 启动。需要双摄时，复制 `smartbag-alert.service` 并改为 `--left-detector`/`--right-detector` 两条命令，同时确认板端算力和两个摄像头设备稳定。
