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
