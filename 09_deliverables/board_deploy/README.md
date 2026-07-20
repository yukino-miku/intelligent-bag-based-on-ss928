# SS928 Rev2 脱机板端部署

正式部署默认是一个 controller、一个 YOLO 模型和左右 USB 摄像头交替采集。Controller 监督视觉、GNSS、BMI270、MR20、执行器、BLE 和本地视频 gateway；任一时刻只打开一侧 UVC，未激活侧是缓存画面。Controller 独占 `SS928-SmartBag` BLE；视频只走本地 LAN，不走 BLE。`smartbag.target` 不依赖电脑、SSH、CloudBase、互联网或 `network-online.target`，也不启动 IMX347、VO 或 MIPI 显示。

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
sudo sh install.sh /path/to/intelligent-bag-based-on-ss928 /合法来源/yolo11n.pt /可选/wheelhouse
```

安装器创建 `/root/smartbag/venv`（直接复用板端 system site packages），模型必须通过第二个参数提供或已存在于正式目录；可选第三个参数是离线 wheelhouse。脚本不会联网下载 `torch/ultralytics/lap`，因为 ARM wheel、Python ABI 和板端镜像必须匹配。归档 SDK、模型和 wheel 不进入 Git。

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

`preflight.sh` 检查两个设备不是同一真实节点、两份标定、模型、依赖、I2C、格式和端口，并按正式交替语义顺序读取左右首帧。UART、PWM、蓝牙、eth1 和音频作为 optional 设备记录 `degraded`，不会阻止本地视觉告警；required 设备等待超时才让 service 失败并由 systemd 重启。等待详情写入 `/run/smartbag/waits/*.json`。

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
journalctl -u smartbag-controller.service -f
```

`smartbag-controller.service` 从配置生成一条 alternating detector 命令，模型只加载一次，左右 tracker/risk/stabilizer/标定仍完全独立。`Restart=always`、`KillMode=control-group` 和绝对路径 venv 保证它不依赖交互 shell。`smartbag-safe-off.service` 在启动和关机执行清除，controller 的 `ExecStopPost` 再做一次 best-effort TM6605 stop、灯光 PWM off 和音频终止。

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

卸载不删除 `/etc/smartbag` 和 `/var/lib/smartbag`。BMI270 I2C blob、模型、真实标定和设备身份信息由用户合法提供。Rev2 音频默认启用但属于 optional；`sample_audio`、I2S pinmux 或 L3/R3/L4/R4 文件缺失时只标记 audio degraded。

## 11. 默认交替双摄模式

当前 Rev2 默认采用单模型交替模式，原因是同一 USB 2.0 Hub 下双路并发 `VIDIOC_STREAMON` 曾返回 `ENOSPC`。它任意时刻只让一个摄像头 STREAMON，未激活侧显示缓存帧，不等同于同步实时双摄，也不能因此宣称已达到安全认证等级。下面的 A/B 工具仍用于诊断，正式启动入口是 `smartbag.target`。

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

打开 `http://<板端地址>:8081/`；顶部“低延迟交替画面”始终显示左右两侧中最新的一帧，下方两个窗口用于观察各侧最近缓存帧和帧龄。`stream_only` 不生成检测 overlay，首页会在左右 overlay 不可用时自动选择 raw，并禁用按钮显示“检测画面不可用”。原始 session 在 `/var/log/smartbag/alternating-camera-runs/<SESSION_ID>/`，包括 `session.json`、`switch-events.csv`、`camera-events.csv`、`performance.csv`、`alerts.csv`、`errors.log` 和 summary。

如果页面黑屏，先分别验证状态、单帧和连续流：

```sh
curl -s http://127.0.0.1:8081/api/v1/status
curl --max-time 3 'http://127.0.0.1:8081/api/v1/alternating/mjpeg?view=raw' -o /tmp/alternating.mjpeg
curl -f 'http://127.0.0.1:8081/api/v1/camera/left/snapshot.jpg?view=raw' -o /tmp/left.jpg
curl --max-time 3 'http://127.0.0.1:8081/api/v1/camera/left/mjpeg?view=raw' -o /tmp/left.mjpeg
```

纯采集时 `raw_available=true`、`overlay_available=false` 是正常状态。snapshot 正常但 MJPEG 长时间只有一个分段时，应检查是否运行了旧版仅按 V4L2 sequence 去重的网关；UVC 每次 STREAMOFF/STREAMON 后 sequence 可能重复，新版同时使用采集和发布时间识别新帧。

实板浏览器预览更适合使用下一档 720p 参数；它仍是交替采集，不是同步双摄：

```sh
sudo env WIDTH=1280 HEIGHT=720 FPS=30 SLICE_MS=400 \
  WARMUP_FRAMES=1 FRAMES_PER_SLICE=6 DURATION_S=3600 \
  sh /root/smartbag/board-deploy/alternating-test.sh \
  --runtime-mode stream_only --serve-bind 0.0.0.0 \
  --serve-port 8081 --stream-fps-limit 10
```

本组实测左右均约 5.8–6.0 capture FPS，较 1080p/4 帧组的约 4.15 FPS 提高约 43%，且无 STREAMON/STREAMOFF 失败。网页左右并排显示：当前侧成批更新，另一侧保持缓存帧，不会把整个页面在左右画面之间闪切。纯摄像头模式会禁用不可用的检测画面按钮，MJPEG 断线后每秒尝试重连。

若重点是低延迟调试，可再降到 `640x480`，把 `--stream-fps-limit` 提高到 30，并优先观察顶部交替流。单侧流天然会在另一侧采集时冻结；这不是以太网带宽不足，也不能通过回放旧帧真正修复。两路相机共用同一 USB 2.0 控制器时，每次 STREAMOFF/STREAMON 的首帧等待仍是主要抖动来源。

若板端和电脑都显示千兆全双工，但 JPEG 下载只有约 1 Mbps 且 `netstat -s` 出现大量 TCP retransmit，可临时限制实际接线网口只协商 100M 全双工作对照。以下 advertisement mask 适用于本次 SS928 实板的 `ethtool`，重启或链路重建后可能恢复，执行前必须先用 `ip route get <PC_IP>` 确认实际接口：

```sh
ip route get 192.168.1.10
sudo ethtool -s eth1 autoneg on advertise 0x008  # 100baseT/Full only
ethtool eth1 | grep -E 'Speed:|Duplex:|Link detected:'

# 恢复本板原来的 10/100/1000 自动协商集合
sudo ethtool -s eth1 autoneg on advertise 0x02f
```

2026-07-20 实测从异常千兆切到 100M 全双工后，20 张 JPEG 吞吐由约 0.7 Mbps 升至 27.3 Mbps；顶部交替流达到约 7.63 FPS，最长帧间隔约 400 ms。该结果说明现场千兆 PHY/网线兼容异常会叠加视频卡顿，但 100M 已足够当前 MJPEG 调试流。不要仅凭小包 ping 判断视频链路正常。

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

正式 `smartbag-controller.service` 内部监督 alternating detector；`smartbag-alternating-vision.service` 仅保留为互斥的独立诊断入口，不与默认 target 同时启动。单进程模型只加载一次，但左右 tracker、轨迹、风险、稳定器、标定和 CSV 均独立。风险优先调度只读取稳定后的 haptic 等级，并保留另一侧最小时间片；无新观测不等于 SAFE。heartbeat 只推进当前有界模式，不重建队列，也不进入 BLE 历史。

## 12. Rev2 硬件 profile

新安装生成 `/etc/smartbag/hardware.json`，默认 `rev2_tm6605_mr20`。旧四路 PWM 振动只能通过兼容 profile 使用：

```sh
sudo /root/smartbag/board-deploy/smartbag-hardware-profile.sh show
sudo /root/smartbag/board-deploy/smartbag-hardware-profile.sh set rev2_tm6605_mr20
sudo /root/smartbag/board-deploy/smartbag-hardware-profile.sh set legacy_pwm_haptics
```

切换脚本停止服务、依赖 controller 退出清输出、备份配置、校验 pin conflict，失败时恢复旧文件和服务。Rev2 中 Pin7/Pin32 是左右灯，不再是振动；左右 LRA 由 TCA9548A CH1/CH2 的 TM6605 驱动。详细接线只以 `04_hardware/ss928/40pin-usage.md` 为准。

输出策略：Level 0 全关；Level 1–4 一一映射为四档触觉模式；Level 3 增加对应侧 50% duty、1000/1000 ms 持续慢闪和 L3/R3 语音；Level 4 增加 80% duty、200/200 ms 持续快闪和 L4/R4 语音。现有可追溯资料只确认 TM6605 地址 `0x2d`、effect 寄存器 `0x04`、play/stop 寄存器 `0x0c` 以及 effect 15/14；未找到可确认的线性 gain/amplitude 寄存器，因此代码用已知 effect 和不同重复周期形成“四档触觉模式”，不声称线性振幅。

## 13. Rev2 预检和物理测试

先只读检查，再由操作员确认供电和接线后显式允许输出：

```sh
sudo sh hardware-preflight.sh /etc/smartbag/hardware.json
sudo sh i2c-mux-test.sh
sh pwm-list.sh
python3 pwm-probe.py --channel 10

# 以下命令会驱动实物，必须确认独立供电、共地、电压和方向
sudo sh tm6605-test.sh left 1 --confirm-live-output
sudo sh tm6605-test.sh left 4 --confirm-live-output
sudo sh tm6605-test.sh right 1 --confirm-live-output
sudo sh tm6605-test.sh right 4 --confirm-live-output
sudo sh light-test.sh left 3 --confirm-live-output
sudo sh light-test.sh right 4 --confirm-live-output
```

PWM `EINVAL` 必须记录实际 pwmchip、npwm、channel、export、period、duty、enable、errno 和 pinmux readback。`pwm-probe.py` 采用 disable -> duty 0 -> period -> duty -> enable，并在退出时关断；不要把 dry-run 或 sysfs 写入成功写成灯具实物响应。

## 14. MR20 网络和回放

默认只配置 `eth1`：板端 `192.168.1.102/32`，右后雷达 `192.168.1.200:2369`，controller 绑定 UDP 2368。先检测实际网络管理器，再显式安装；脚本不会给 eth1 配网关或默认路由：

```sh
sudo sh mr20-network-install.sh --apply
sh mr20-network-preflight.sh
sh mr20-capture.sh --duration-s 30 --output /var/log/smartbag/radar-frames.csv
python3 /root/smartbag/mr20_radar/mr20_replay.py \
  --config /etc/smartbag/mr20-radar.json \
  /root/smartbag/mr20_radar/tests/fixtures/official-example.hex
```

不要同时让 systemd-networkd 和 NetworkManager 管理 eth1。`ping` 或 0x60A 只证明链路；必须捕获真实 0x60B、验证距离/速度/TTC、多帧 clear，再验证 `radar:right_rear` 到 controller、TM6605、灯光和 BLE 的闭环。

## 15. 可选 CloudBase

`smartbag-cloud-uploader.service` 默认不在 `smartbag.target`。编辑 `/etc/smartbag/cloud-uploader.json`，保持 secret 不在 JSON 中；在权限受限的 `/etc/smartbag/cloud-uploader.env` 写入环境变量后才启用：

```sh
sudo install -m 0600 /dev/null /etc/smartbag/cloud-uploader.env
# 在本机交互式编辑：SMARTBAG_HMAC_SECRET=...
sudo systemctl enable --now smartbag-cloud-uploader.service
```

小程序真实 EnvId/deviceId 放在被忽略的 `miniprogram/config/cloud.local.js`。云函数使用 `cloud.getWXContext()` 和 `device_bindings`，设备上传使用 HTTPS/HMAC/timestamp/nonce/body SHA256。Cloud 失败会回退 BLE；视频仍通过局域网 HTTP/MJPEG，禁止上传连续视频到 CloudBase。未实际部署函数、集合、TTL 和绑定前，状态只能写 `NOT DEPLOYED`。

## 16. Session 和回滚

```sh
sudo sh full-hardware-test.sh
sudo env DURATION_S=1800 sh full-hardware-test.sh  # 30 分钟只读资源/日志采样
sudo /root/smartbag/venv/bin/python /root/smartbag/board-deploy/rev2-board-validation.py --phase preflight
# 确认供电、共地和接线后，才允许自动执行物理输出阶段
sudo /root/smartbag/venv/bin/python /root/smartbag/board-deploy/rev2-board-validation.py --all --allow-live-output
sudo sh smartbag-hardware-profile.sh set legacy_pwm_haptics  # 旧硬件回滚
# 编辑 /etc/smartbag/hardware.json: hardware.radar.enabled=false
# 编辑 /etc/smartbag/cloud-uploader.json: enabled=false
```

validation 支持 `preflight/i2c/haptics/lights/audio/gnss/imu/radar/camera/vision/ble/integration/boot/all`。session 在仓库运行时进入 Git 忽略的 `08_media/rev2-autonomous/<SESSION_ID>/`，板端进入 `/var/log/smartbag/rev2-validation/`；开机自检写 `/var/log/smartbag/boot-selftest/latest.json`。只有真实执行并保存日志的项目可标 `BOARD TESTED` 或 `PHYSICALLY VERIFIED`；I2C 写成功最多是 `ELECTRICALLY EXERCISED`，不能代替振幅或灯光实物反馈。

Controller 将状态变化写入 `/var/log/smartbag/actuator-events.jsonl`，字段包含 source event、controller receive、effective/haptic/light level、light mode、audio clip、实际 TM6605/PWM 写完成和 BLE transmit 的 monotonic 时间；只有时钟域一致且实际发生写入时才计算时延。Level 1/2 会写 TM6605，但灯光和音频保持关闭。

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

固定双 detector 只作为兼容诊断模式：先停止 `smartbag.target`，再显式修改 `vision_runtime.mode=fixed_dual_process`。Rev2 默认仍是 alternating。紧急安全清除执行：

```sh
sudo systemctl stop smartbag.target smartbag-controller.service smartbag-alternating-vision.service
sudo /root/smartbag/venv/bin/python /root/smartbag/board-deploy/safe_off.py --hardware /etc/smartbag/hardware.json
```

随后用 `fuser /dev/video0 /dev/video2` 确认两路均无占用。默认配置不等于实板验收：必须实际 enable target、断开电脑、完成两次断电/重启并检查 controller、safe-off、boot-selftest 和执行器清零，才能声明 `POWER_ONLY_AUTOSTART_READY`。
