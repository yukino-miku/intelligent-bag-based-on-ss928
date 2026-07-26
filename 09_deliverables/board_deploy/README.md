# SS928 智能背包板端部署

正式部署默认是两路固定方向 detector：左/右 USB camera 分别由唯一 detector 持有。Controller 独占 `SS928-SmartBag` BLE、TM6605/LRA、Pin7/Pin32 灯、可选 MR20 和 MAX98357；视频只走 Wi-Fi/LAN。`smartbag.target` 不启动 IMX347、VO、MIPI 显示或交替双摄入口。

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

2026-07-16 的历史实板基线中，两台 `0bda:3035` 序列号相同且共用 USB 2.0 hub，并发时出现 `VIDIOC_STREAMON: ENOSPC`。更换端口后必须重新运行 `camera-list.sh` 和 preflight；历史节点和拓扑不能当作当前接线事实。

## 2. 依赖和安装

```sh
cd /path/to/intelligent-bag-based-on-ss928/09_deliverables/board_deploy
sudo sh install-deps.sh                 # 只检查，不安装
sudo sh install-deps.sh --install-system # 可选：安装 apt 中的系统包
sudo sh install.sh /path/to/intelligent-bag-based-on-ss928
sudo install -m 0644 /合法来源/yolo11n.pt /root/smartbag/models/yolo11n.pt
```

首次安装可选硬件 profile；profile 只是对默认配置的递归覆盖，不包含 secret：

```sh
sudo env SMARTBAG_HARDWARE_PROFILE="$PWD/profiles/dual-usb-base.json" \
  sh install.sh /path/to/intelligent-bag-based-on-ss928
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

`pwm_channels` 仅保留旧配置兼容。正式 `outputs.haptics_backend=tm6605` 时，TCA9548A 地址默认 0x70，BMI270/左 TM6605/右 TM6605 分别使用 channel 0/1/2；灯使用 Pin7/Pin32。Pin35/Pin37 只在显式选择 legacy PWM backend 时使用。接线以 `04_hardware/ss928/40pin-usage.md` 为唯一事实源。

可选模块：

- `radar.enabled=false` 为默认；启用前编辑 `/etc/smartbag/mr20.json`，确认每个 radar 的 IP、bind port、side 和 networkd 路由。示例 network 文件不会自动安装。
- `modules.gnss.enabled=false` 为基线；修复/接入 DX-GP21 并验证 `/dev/ttyAMA4` 后再启用。
- `modules.imu.enabled=true`；不要另启旧 BMI service。
- `audio.enabled=false`；确认 MAX98357、I2S pinmux 和素材许可后再启用。
- `/etc/smartbag/smartbag.env` 必须 root:root 0600；MT5710、Cloud token、告警号码和 WS73 路径均在这里配置。

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

`smartbag-alert.service` 由配置生成两条等价于 `--left-detector`/`--right-detector` 的固定侧命令。子进程 stdout 只承载 JSONL。任一 detector 退出会先清本侧 vision source，再有限退避重启；同侧 MR20 或另一侧继续。事件过期、level=0、SIGTERM、异常和 `ExecStopPost` safe-off 都会清振/灯。

`smartbag.target` 必需 alert 与 video，按条件拉起 WS73 module loader、MT5710 connectivity 和 temperature。MT5710 service 只拥有 NCM，不启动 BMI/GNSS；Cloud/5G 失败不会停止本地告警。驼背 `REMINDER,HUNCH` 会以 `posture:hunch` 独立来源触发双侧轻振 5 秒，可选播放 `bad` 音频，不覆盖交通风险。

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

Ultralytics 的当前调用把推理与 BoT-SORT 组合在 `model.track()` 内，因此 profile 记录为 `infer+track`，不虚构无法可靠分开的 tracker 时间。2026-07-16 历史镜像只有约 952 MiB 内存且缺少视觉依赖；部署时必须重新检查当前镜像。

`vision/ss928_backend` 的 ACL/OM 代码目前只验收到离线 detections JSONL。来源固定输入性能不等于真实检测正确，也不等于双 USB NPU 实时链。真实 OM、camera-to-NV12、双路调度以及 detections-to-BoT-SORT/risk bridge 验收前，正式实时后端仍使用 Python Ultralytics。

## 10. 停止和卸载

```sh
sudo sh stop-all.sh
sudo sh uninstall.sh
```

卸载不删除 `/etc/smartbag` 和 `/var/lib/smartbag`。升级使用 `upgrade.sh` 和 `migrate_config.py` 保留本地值；需要切换 profile 时先备份配置，再运行 `apply_hardware_profile.py`。BMI270 blob、模型、真实标定、设备身份和 secret 均由用户合法提供。
