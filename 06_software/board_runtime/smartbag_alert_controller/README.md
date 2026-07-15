# SmartBag Alert Controller

板端统一控制器读取视觉 `vision_alert` JSONL，驱动左右四路 PWM，并可选播放 MAX98357 音频。默认由它独占 `SS928-SmartBag` Nordic UART Service，同时路由 GNSS/IMU 命令。

## 安全行为

- 只接受 detector 多帧稳定后的 `haptic_level`，不使用 raw risk。
- 拒绝格式错误、过旧和 0..4 范围外事件。
- 同一 side 的 level=0、事件超时、detector 退出、SIGINT/SIGTERM 和异常都会关闭震动。
- 启动时先清零四路 PWM；音频默认关闭且在独立线程播放。
- PWM 等级、占空比、周期、超时和音频开关来自 JSON 配置。

## 单摄默认模式

```sh
cd /root/smartbag/controller
python3 smartbag_alert_controller.py \
  --config /etc/smartbag/config.json \
  --single-camera \
  --detector "python3 /root/smartbag/vision/vision_obstacle_tracker.py --source camera --camera-device /dev/video0 --runtime-profile board_cpu --model /root/smartbag/models/yolo11n.pt --no-display" \
  --detector-cwd /root/smartbag/vision \
  --gnss-command "python3 /root/smartbag/gnss/dx_gp21_tracker.py --config /root/smartbag/gnss/config.ss928_uart4.json --command-stdin --no-ble" \
  --imu-command "python3 /root/smartbag/imu/bmi270_backpack.py --config /root/smartbag/imu/config.example.json --command-stdin --no-ble"
```

Controller 自动追加 `--side auto --emit-alert-jsonl`。双摄兼容模式改用 `--left-detector` 和 `--right-detector`；板端算力不足时不要默认启动两套 YOLO。

无硬件测试：

```sh
printf '%s\n' '{"type":"vision_alert","side":"left","level":3,"score":0.75,"track_id":1,"ts":1.0}' 'AL CLEAR' | \
  python3 smartbag_alert_controller.py --dry-run --stdin-jsonl --no-ble
```

接线不在本目录重复定义，以 `04_hardware/ss928/40pin-usage.md` 为准。正式部署使用 `09_deliverables/board_deploy`。
