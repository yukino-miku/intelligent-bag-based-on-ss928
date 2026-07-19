# SS928 双 USB 摄像头板端部署

正式部署默认是两路固定方向 detector：左 USB 摄像头只控制左侧 PWM，右 USB 摄像头只控制右侧 PWM。Controller 独占 `SS928-SmartBag` BLE；视频只走 Wi-Fi/LAN，不走 BLE。`smartbag.target` 不启动 IMX347、VO 或 MIPI 显示。

## 1. 准备两路摄像头

优先把两个 UVC 摄像头接到不同 USB 3.0 根控制器。物理端口是否独立必须用 `lsusb -t` 实测，不能按接口外观判断。

```sh
sh camera-list.sh
v4l2-ctl --list-devices
ls -l /dev/v4l/by-id/
ls -l /dev/v4l/by-path/
v4l2-ctl --device /dev/video0 --list-formats-ext
v4l2-ctl --device /dev/video2 --list-formats-ext
```

序列号唯一时推荐 `/dev/v4l/by-id/...-video-index0`，避免重启后 `/dev/video0`、`video2` 交换。相同型号摄像头若序列号相同，by-id 会冲突，此时必须改用两个不同的 `/dev/v4l/by-path/...` 并固定物理 USB 口。不要把同一真实设备的两个别名配置为左右相机。

2026-07-16 当前实板的两台 `0bda:3035` 摄像头序列号完全相同，且都位于 `10320000.xhci_1` 下的同一 USB 2.0 hub。并发 640x480 与 320x240 MJPEG 都出现一侧 `VIDIOC_STREAMON: ENOSPC`。正式测试前必须把其中一台移动到另一 xHCI 根路径，再用 `camera-list.sh` 和 preflight 复核；只看到两个 `/dev/video*` 节点不代表双路可同时工作。

## 2. 依赖和安装

```sh
cd /path/to/intelligent-bag-based-on-ss928/09_deliverables/board_deploy
sudo sh install-deps.sh                 # 只检查，不安装
sudo sh install-deps.sh --install-system # 可选：安装 apt 中的系统包
sudo sh install.sh /path/to/intelligent-bag-based-on-ss928
sudo install -m 0644 /合法来源/yolo11n.pt /root/smartbag/models/yolo11n.pt
```

脚本不会在线安装 `torch/ultralytics/lap`，因为 ARM wheel、Python ABI 和板端镜像必须匹配。先运行 `check-runtime-deps.sh`，再使用经过板端验证的本地 wheel 或镜像包。归档 SDK、模型和 wheel 不会复制进 Git。

## 3. 配置左右相机和标定

编辑 `/etc/smartbag/config.json`：

```json
{
  "cameras": {
    "left": {
      "camera_device": "/dev/v4l/by-id/LEFT-video-index0",
      "detector_profile": "board_dual_balanced",
      "calibration_file": "/etc/smartbag/calibration-left.json",
      "stream_port": 18081,
      "pwm_channels": ["left_1", "left_2"]
    },
    "right": {
      "camera_device": "/dev/v4l/by-id/RIGHT-video-index0",
      "detector_profile": "board_dual_balanced",
      "calibration_file": "/etc/smartbag/calibration-right.json",
      "stream_port": 18082,
      "pwm_channels": ["right_1", "right_2"]
    }
  },
  "stream_gateway": {"bind": "0.0.0.0", "port": 8080, "access_token": ""}
}
```

安装生成的两个 calibration 文件只是可编辑模板，不含伪造的内参。必须分别填写左右相机的 `camera_matrix`、畸变、实际安装高度和 pitch；两台相机的高度、朝向、FOV 和畸变不能默认相同。先修正标定，再调整风险阈值。

默认 `board_dual_balanced` 请求摄像头已枚举支持的 640x480@30、YOLO `imgsz=512`、推理上限 8 FPS；手机预览在配置示例中独立缩放到 480x360、JPEG quality 70、每客户端最多 8 FPS。`board_cpu` 同样使用 640x480，YOLO `imgsz=416`。摄像头描述符中的 30 FPS 不是持续性能保证；当前同路 hub 的单摄底层短测仅约 7.5–8.4 FPS。

## 4. 部署前检查

停止正在使用摄像头或端口的服务，再执行：

```sh
sudo systemctl stop smartbag.target 2>/dev/null || true
sudo sh check-runtime-deps.sh
sudo sh preflight.sh /etc/smartbag/config.json
```

`preflight.sh` 检查两个设备不是同一真实节点、两份标定、模型、依赖、PWM/I2C/UART/蓝牙、格式和端口，并并发读取左右首帧。它不能替代 30 分钟以上的双摄 FPS、温度和掉线测试。

## 5. 无摄像头模拟双路

```sh
sudo sh dual-vision-test.sh /path/left.mp4 /path/right.mp4 /etc/smartbag/config.json
```

该命令使用 `--left-video/--right-video`、dry-run PWM、no-BLE，仍启动两个独立 detector。视频文件必须由用户本地提供，不进入 Git。

## 6. 正式启动和日志

```sh
sudo systemctl enable --now smartbag.target
sh status.sh
sh logs.sh -f
journalctl -u smartbag-alert.service -f
```

`smartbag-alert.service` 由配置生成两条等价于 `--left-detector`/`--right-detector` 的固定侧命令。子进程日志带 `[left]`、`[right]`，其 stdout 只承载 JSONL。任一 detector 退出会先清本侧 PWM，再有限次数指数退避重启；另一侧继续运行。事件过期、level=0、SIGTERM 和异常也会清振。

## 7. 双路视频接口

```sh
curl http://127.0.0.1:8080/api/v1/status
curl http://127.0.0.1:8080/api/v1/cameras
curl http://127.0.0.1:8080/api/v1/camera/left/status
curl http://127.0.0.1:8080/api/v1/camera/right/status
sh stream-test.sh 127.0.0.1 8080
```

浏览器调试页：`http://<BOARD_IP>:8080/`；启用 token 后使用 `http://<BOARD_IP>:8080/?token=<TOKEN>`。snapshot：

```text
/api/v1/camera/left/snapshot.jpg?view=overlay
/api/v1/camera/right/snapshot.jpg?view=overlay
/api/v1/camera/left/snapshot.jpg?view=raw
/api/v1/camera/right/snapshot.jpg?view=raw
```

连续 MJPEG 基线为 `/api/v1/camera/{left|right}/mjpeg?view=overlay`。外部 gateway 不打开摄像头，只代理 detector 的最新帧；没有客户端时不主动 JPEG 编码。访问令牌可在 config 中设置，正式公网场景仍需 HTTPS、认证和防火墙，本服务默认只面向可信局域网。

## 8. 微信小程序

在微信开发者工具导入 `06_software/mobile/ssminiprogram`，进入“**双摄实时画面**”，填写板端 IP/主机名、端口、可选 token 和刷新 FPS。设置通过 `wx.setStorageSync` 保存，不写死设备 IP。页面支持左右同时显示、raw/overlay、暂停/恢复、重连、状态和单侧预览。

开发者工具可临时关闭域名/TLS 校验。正式真机必须使用实际 AppID，并根据微信当前规则验证局域网 IP、合法域名和 HTTPS；游客 AppID 或调试模式成功不代表发布版成功。手机与板端必须处于可互访网络，AP 客户端隔离需要关闭。BLE 仍只传告警、GNSS、IMU 和 `SYS STATUS`。

## 9. 性能降级顺序

先查看 `/api/v1/status` 和两侧 profile，再逐项调整：

1. 降低 `stream_fps_limit` 或小程序 `refreshFps`，只减少视频传输，不降低 YOLO 输入质量。
2. 降低 `jpeg_stream_width/height` 或 `jpeg_quality`，只减少 JPEG/网络开销。
3. 降低 `inference_fps_limit`，采集线程仍持续排空并只交付最新帧。
4. 设置 `process_every_n=2`，明确降低推理采样频率，但不会积压旧帧。
5. 最后才把 detector profile 回退为 `board_cpu`。

Ultralytics 的当前调用把推理与 BoT-SORT 组合在 `model.track()` 内，因此 profile 记录为 `infer+track`，不虚构无法可靠分开的 tracker 时间。当前板上只有约 952 MiB 总内存，并缺少 cv2/torch/ultralytics/lap；现有数据只覆盖底层 UVC 短测，不是双路 detector 的 CPU、内存、FPS、温度或 NPU 性能。

## 10. 停止和卸载

```sh
sudo sh stop-all.sh
sudo sh uninstall.sh
```

卸载不删除 `/etc/smartbag` 和 `/var/lib/smartbag`。BMI270 I2C blob、模型、真实标定和设备身份信息由用户合法提供。音频默认关闭。

## 11. 实验性交替双摄模式

当两台相机位于同一 USB 2.0 Hub、第二路 `VIDIOC_STREAMON` 返回 `ENOSPC` 时，可测试单模型交替模式。它任意时刻只让一个摄像头 STREAMON，未激活侧显示缓存帧，不等同于同步实时双摄，也不适合作为最终高安全等级方案。

先停止正式服务并运行无模型矩阵：

```sh
sudo systemctl stop smartbag.target smartbag-alternating-vision.service
sudo env \
  LEFT_DEVICE=/dev/v4l/by-path/LEFT-video-index0 \
  RIGHT_DEVICE=/dev/v4l/by-path/RIGHT-video-index0 \
  DURATION_S=120 \
  sh /root/smartbag/board-deploy/alternating-experiment-matrix.sh
sh /root/smartbag/board-deploy/alternating-report.sh
```

无模型缓存预览可直接追加参数：

```sh
sudo env LEFT_DEVICE=/dev/v4l/by-path/LEFT-video-index0 \
  RIGHT_DEVICE=/dev/v4l/by-path/RIGHT-video-index0 \
  DURATION_S=120 \
  sh /root/smartbag/board-deploy/alternating-test.sh \
  --runtime-mode stream_only --serve-bind 0.0.0.0 --serve-port 8081
```

打开 `http://<板端地址>:8081/`；非 active 侧是最后缓存帧，页面会显示帧龄。原始 session 在 `/var/log/smartbag/alternating-camera-runs/<SESSION_ID>/`，包括 `session.json`、`switch-events.csv`、`camera-events.csv`、`performance.csv`、`alerts.csv`、`errors.log` 和 summary。

只有板端视觉依赖和模型已经通过 `check-runtime-deps.sh` 时，才允许配置 C/D：

```json
{
  "vision_runtime": {"mode": "alternating_single_model"},
  "alternating_camera": {
    "enabled": true,
    "backend": "v4l2_stream_toggle",
    "inference_frames_per_slice": 1,
    "normal_slice_ms": 500,
    "risk_slice_ms": 700,
    "minimum_other_side_slice_ms": 250,
    "max_blind_interval_ms": 1200,
    "stale_observation_timeout_ms": 1800,
    "tracker_effective_fps_mode": "effective_side",
    "min_confirm_slices_caution": 2,
    "min_confirm_slices_danger": 2,
    "min_confirm_slices_emergency": 2,
    "camera_reconnect_enabled": true,
    "video_gateway_enabled": true,
    "serve_bind": "0.0.0.0",
    "serve_port": 8080,
    "calibration_mode": "production",
    "risk_priority_enabled": true
  }
}
```

启动、状态、日志和报告：

```sh
sudo sh /root/smartbag/board-deploy/alternating-start.sh /etc/smartbag/config.json
sh /root/smartbag/board-deploy/alternating-status.sh
sh /root/smartbag/board-deploy/alternating-logs.sh -f
sh /root/smartbag/board-deploy/alternating-report.sh
```

`smartbag-alternating-vision.service` 与正式 `smartbag-alert.service`、`smartbag-video.service` 互斥。单进程模型只加载一次，但左右 tracker、轨迹、风险、稳定器、标定和 CSV 均独立。风险优先调度只读取稳定后的 haptic 等级，并保留另一侧最小时间片；无新观测不等于 SAFE。heartbeat 只维持 PWM，不进入 BLE 历史；超时、连续切换失败、detector 退出和 SIGTERM 都会清振。

`--inference-frames-per-slice` 默认只选择每片最后一张最新帧，采集到的其余有效帧只计入采集统计，不进入积压队列。`capture_only_max_blind_ms` 是纯 STREAMOFF/STREAMON/首帧指标；`end_to_end_max_gap_ms` 才包含解码、模型、tracker、风险、overlay、JPEG 和下一轮调度，正式验收只看后者。CAUTION 以上普通升级需要跨不同 slice，避免同一 burst 快速满足多帧确认。

交替 detector 自己提供 `http://<BOARD_IP>:8080/`，无需 `smartbag-video.service`。页面同时显示左右 raw/overlay、active/cached/offline、帧龄、推理 FPS、风险和 E2E 间隔。测试接口：

```sh
curl -f 'http://127.0.0.1:8080/api/v1/camera/left/snapshot.jpg?view=raw' -o /tmp/left-raw.jpg
curl -f 'http://127.0.0.1:8080/api/v1/camera/right/snapshot.jpg?view=raw' -o /tmp/right-raw.jpg
curl -f 'http://127.0.0.1:8080/api/v1/camera/left/snapshot.jpg?view=overlay' -o /tmp/left-overlay.jpg
curl -f 'http://127.0.0.1:8080/api/v1/camera/right/snapshot.jpg?view=overlay' -o /tmp/right-overlay.jpg
```

raw 复用摄像头 MJPEG，overlay 是视觉完成后重新编码的带框图。只有 C 阶段模型实际运行时，overlay 才能用于验收检测框。客户端断开不会停止 detector，gateway 也不会重开相机。

启动前运行 `alternating-preflight.sh`。它检查实验开关、左右设备不相同且未占用、模型/两份标定、production 外参、依赖、HTTP 端口和 PWM 基础节点。依赖安装见 `install-board-cpu-deps.sh` 和 `install-board-deps-offline.sh`；后者只接受本地 wheelhouse，并打印 wheel SHA256。详细 ABI 和 NPU 阻塞项见 `02_research/ss928-runtime-dependencies.md` 与 `02_research/ss928-om-backend-blockers.md`。

一侧失败后，调度器只关闭并重开该侧；另一侧继续。switch CSV 记录 connection state、disconnect/reconnect 时间、恢复耗时、首个恢复帧耗时和 tracker reset。生成 clear 事件不等于 PWM 已经清零；`camera_offline_clear_verified` 只有 controller/PWM 闭环测试有确认时才能是 true，否则保持 null。

`cleanup-alternating-runs.sh` 配合 timer 限制 session 数量和总大小，并在服务运行时跳过最新活动目录。正式配置默认 `risk_csv_enabled=false`；安装脚本写入 `/etc/systemd/journald.conf.d/smartbag.conf`，限制持久 journal 100 MiB、运行时 32 MiB、最长保留 7 天，卸载时会移除该 drop-in。

回退到正式模式：先运行 `alternating-stop.sh`，把配置改回 `vision_runtime.mode=fixed_dual_process` 和 `alternating_camera.enabled=false`，再执行 `sudo systemctl start smartbag.target`。紧急停振执行：

```sh
sudo systemctl stop smartbag-alternating-vision.service smartbag-alert.service smartbag.target
```

随后用 `fuser /dev/video0 /dev/video2` 确认两路均无占用。30 分钟和 C/D 的真实结果以 `07_tests/results/alternating_camera/latest-summary.md` 为准；只要模型、完整 E2E、PWM、BLE、拔插恢复或完整视觉长测仍有一项未通过，就不得把实验模式设为默认。
