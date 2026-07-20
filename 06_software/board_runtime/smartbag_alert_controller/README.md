# SmartBag Alert Controller

板端统一控制器读取两个固定方向 detector 的 `vision_alert` JSONL，左事件只驱动 `left_1/left_2`，右事件只驱动 `right_1/right_2`。它独占 `SS928-SmartBag` BLE NUS，同时路由 GNSS/IMU 命令；视频不进入 BLE。

## 正式双摄模式

```sh
python3 smartbag_alert_controller.py \
  --config /etc/smartbag/config.json \
  --detector-cwd /root/smartbag/vision \
  --gnss-command "python3 /root/smartbag/gnss/dx_gp21_tracker.py --config /root/smartbag/gnss/config.ss928_uart4.json --command-stdin --no-ble" \
  --imu-command "python3 /root/smartbag/imu/bmi270_backpack.py --config /root/smartbag/imu/config.example.json --hardware-profile /etc/smartbag/hardware.json --command-stdin --no-ble"
```

Controller 从 `cameras.left/right` 生成等价于 `--left-detector` 和 `--right-detector` 的命令，固定追加 `--side left|right --emit-alert-jsonl`。也可手动覆盖：

```sh
python3 smartbag_alert_controller.py --dry-run --no-ble --skip-pinmux \
  --left-detector "python3 /root/smartbag/vision/vision_obstacle_tracker.py --source camera --camera-device /dev/video0 --runtime-profile board_dual_balanced --no-display" \
  --right-detector "python3 /root/smartbag/vision/vision_obstacle_tracker.py --source camera --camera-device /dev/video2 --runtime-profile board_dual_balanced --no-display"
```

旧 `--single-camera --detector ... --side auto` 仅保留兼容测试，不用于默认 systemd。视频模拟使用 `--left-video left.mp4 --right-video right.mp4`，仍保持两套 tracker、风险模型和 stabilizer 相互独立。

## 安全行为

- 只接受 detector 多帧稳定后的 `haptic_level`，不使用 raw risk。
- 固定侧子进程拒绝跨侧事件；一个 detector 退出只清本侧，另一侧保持运行。
- level=0、事件超时、detector 退出、SIGINT/SIGTERM 和异常都会关闭对应 PWM。
- 子进程只做有限次数、带退避的重启；错误 JSON 和过旧事件只记录并丢弃。
- 启动和最终退出均清零四路 PWM；音频默认关闭并在独立线程播放。
- `class`、`distance_m` 是兼容旧 parser 的可选字段，并随自动 alert 推送到 BLE。
- `SYS STATUS` 返回左右等级、detector PID/重启数、模块、CPU、内存、温度和 `battery:null`；没有电池传感器时不伪造百分比。

## 无硬件协议测试

```sh
printf '%s\n' \
  '{"type":"vision_alert","side":"left","level":3,"score":0.75,"track_id":1,"class":"car","distance_m":4.2}' \
  'AL CLEAR' | \
  python3 smartbag_alert_controller.py --dry-run --stdin-jsonl --no-ble --skip-pinmux
```

接线只以 `04_hardware/ss928/40pin-usage.md` 为准。正式部署、依赖、双摄和视频接口见 `09_deliverables/board_deploy/README.md`。
