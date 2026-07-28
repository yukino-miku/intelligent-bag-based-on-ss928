# SmartBag Alert Controller

板端统一控制器的正式候选模式是 `radar_primary_visual_classification`：双 MR20 持续输出目标运动，一个共享 YOLO/OM 实例交替识别左右快照车型，融合层复用原 RiskModel 和逐轨迹 stabilizer，再把每侧最高稳定 haptic 等级交给执行器。Controller 独占 `SS928-SmartBag` BLE NUS，同时路由 GNSS/IMU 命令。

## 雷达主导正式候选模式

```sh
python3 smartbag_alert_controller.py \
  --config /etc/smartbag/config.json \
  --detector-cwd /root/smartbag/vision
```

配置必须指定 `runtime_mode`、两路 MR20、两个稳定 `/dev/v4l/by-path`、左右融合标定、单个 OM/runner 和输出硬件。新模式不会创建旧 detector 子进程，也不会调用旧 MR20 简单 TTC evaluator；摄像头或模型失败时仍以 `unknown=1.0` 计算雷达风险。

## 回归模式

`legacy_dual_vision` 保留旧视觉主导链用于录像和回归。此模式才会从 `cameras.left/right` 生成两个 detector 命令，也可手动覆盖：

```sh
python3 smartbag_alert_controller.py --dry-run --no-ble --skip-pinmux \
  --left-detector "python3 /root/smartbag/vision/vision_obstacle_tracker.py --source camera --camera-device /dev/v4l/by-path/LEFT-video-index0 --runtime-profile board_dual_balanced --no-display" \
  --right-detector "python3 /root/smartbag/vision/vision_obstacle_tracker.py --source camera --camera-device /dev/v4l/by-path/RIGHT-video-index0 --runtime-profile board_dual_balanced --no-display"
```

旧 `--single-camera --detector ... --side auto` 仅保留兼容测试，不用于默认 systemd。视频模拟使用 `--left-video left.mp4 --right-video right.mp4`，仍保持两套 tracker、风险模型和 stabilizer 相互独立。

## 安全行为

- 只接受 detector 多帧稳定后的 `haptic_level`，不使用 raw risk。
- 融合模式同样逐雷达轨迹多帧确认；车型变化不能绕过 stabilizer。
- 未变化的定期保活事件标为 `heartbeat`：维持执行器超时状态，但小程序不重复写告警历史。
- 固定侧子进程拒绝跨侧事件；一个 detector 退出只清本侧，另一侧保持运行。
- level=0、事件超时、detector 退出、SIGINT/SIGTERM 和异常都会关闭对应 PWM。
- 子进程只做有限次数、带退避的重启；错误 JSON 和过旧事件只记录并丢弃。
- 启动和最终退出均清零四路 PWM；音频默认关闭并在独立线程播放。
- BLE 保留旧字段，并可附带雷达 track、车型/权重、距离、速度、TTC/CPA、绑定状态和关联代价。
- `SYS STATUS` 返回左右等级、detector PID/重启数、模块、CPU、内存、温度和 `battery:null`；没有电池传感器时不伪造百分比。

## 无硬件协议测试

```sh
printf '%s\n' \
  '{"type":"vision_alert","side":"left","level":3,"score":0.75,"track_id":1,"class":"car","distance_m":4.2}' \
  'AL CLEAR' | \
  python3 smartbag_alert_controller.py --dry-run --stdin-jsonl --no-ble --skip-pinmux
```

接线只以 `04_hardware/ss928/40pin-usage.md` 为准。正式部署、依赖、双摄和视频接口见 `09_deliverables/board_deploy/README.md`。
