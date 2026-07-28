# SS928 智能背包板端部署

正式候选部署默认使用 `radar_primary_visual_classification`：双 MR20 持续提供目标运动数据，一个 YOLO/OM 模型交替处理左右 USB 快照并只绑定车辆类型。任意时刻最多一路 UVC STREAMON，不运行视觉测距、视觉测速或 BoT-SORT。Controller 独占融合运行时、`SS928-SmartBag` BLE、TM6605/LRA、Pin7/Pin32 灯和可选 MAX98357；`legacy_dual_vision` 只保留回归。

## 1. 准备两路摄像头

两个 UVC 摄像头应固定物理端口，并使用不同 `/dev/v4l/by-path`。新模式不会同时 STREAMON，但物理节点映射仍必须在每次换口后重新确认。

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
sudo env SMARTBAG_MODEL_SOURCE=/合法来源/vehicle-detector.om \
  sh install.sh /path/to/intelligent-bag-based-on-ss928
```

首次安装可选硬件 profile；profile 只是对默认配置的递归覆盖，不包含 secret：

```sh
sudo env SMARTBAG_HARDWARE_PROFILE="$PWD/profiles/dual-usb-base.json" \
  sh install.sh /path/to/intelligent-bag-based-on-ss928
```

正式 OM 快照后端不需要 Torch/BoT-SORT，但需要板端可用的 OpenCV/NumPy、ACL runtime、编译后的 `ss928_detection_runner` 和合法车辆 OM。PC 回放可以使用 Ultralytics。归档 SDK、模型和 wheel 不会复制进 Git。

## 3. 配置雷达、相机和融合标定

编辑 `/etc/smartbag/config.json`：

```json
{
  "runtime_mode": "radar_primary_visual_classification",
  "snapshot_classifier": {
    "backend": "ss928_om",
    "model": "/root/smartbag/models/vehicle-detector.om",
    "imgsz": 640,
    "inference_timeout_ms": 5000,
    "target_switch_interval_s": 0.20,
    "initial_warmup_frames": 2,
    "switch_warmup_frames": 0,
    "capture_timeout_ms": 1000,
    "streamoff_timeout_ms": 1000,
    "left_device": "/dev/v4l/by-path/LEFT-video-index0",
    "right_device": "/dev/v4l/by-path/RIGHT-video-index0"
  },
  "fusion": {
    "left_calibration": "/etc/smartbag/fusion-left.json",
    "right_calibration": "/etc/smartbag/fusion-right.json",
    "projection_half_width_px": 80,
    "bbox_expand_ratio": 0.25,
    "risk_window_s": 0.5,
    "warning_sensitivity": 1.0,
    "debug_port": 8080
  },
  "radar": {"enabled": true, "config": "/etc/smartbag/mr20.json"}
}
```

`pwm_channels` 仅保留旧配置兼容。正式 `outputs.haptics_backend=tm6605` 时，TCA9548A 地址默认 0x70，BMI270/左 TM6605/右 TM6605 分别使用 channel 0/1/2；灯使用 Pin7/Pin32。Pin35/Pin37 只在显式选择 legacy PWM backend 时使用。接线以 `04_hardware/ss928/40pin-usage.md` 为唯一事实源。

可选模块：

- MR20 是新模式的运动数据源。编辑 `/etc/smartbag/mr20.json`，逐侧确认 IP、bind port、side、反向标记、安装偏移和 yaw；示例 network 文件不会自动安装。
- `modules.gnss.enabled=false` 为基线；修复/接入 DX-GP21 并验证 `/dev/ttyAMA4` 后再启用。
- `modules.imu.enabled=true`；不要另启旧 BMI service。
- `audio.enabled=false`；确认 MAX98357、I2S pinmux 和素材许可后再启用。
- `/etc/smartbag/smartbag.env` 必须 root:root 0600；MT5710、Cloud token、告警号码和 WS73 路径均在这里配置。

安装生成的 `fusion-left/right.json` 只是模板，不含实测内外参。必须分别填写相机内参/畸变、FOV、相机位姿、雷达位姿以及 `radar_to_camera_rotation/translation`。安装高度相近不能代替联合标定。

融合模式默认按 640x480 请求每侧 UVC 快照。Linux 原生 V4L2 会预先打开两个 fd 并分配两套 mmap buffer，但任意时刻最多一路 STREAMON；首次丢弃 `initial_warmup_frames`，后续切换默认不丢帧。相邻侧开始时间目标为 0.20 秒，超时不排队而是立即切下一侧并记录 overrun。摄像头描述符中的 FPS 和 0.20 秒目标都不是持续性能保证，必须从状态接口实测。

当前审计选中的 YOLO11n OM 与输出后处理兼容，但静态 AIPP 是 `RGB_PLANAR`，现有 runner 输入是 NV12，因此 manifest 会让 preflight 明确失败。先完成 runner 输入适配或重新转换并做 ACL 实板验证，再把 manifest 的兼容状态改为 true；不能仅因为 `.om` 存在就启动正式服务。

## 4. 部署前检查

停止正在使用摄像头或端口的服务，再执行：

```sh
sudo systemctl stop smartbag.target 2>/dev/null || true
sudo sh check-runtime-deps.sh /etc/smartbag/config.json
sudo sh preflight.sh /etc/smartbag/config.json
```

`preflight.sh` 在融合模式检查两个设备不是同一真实节点、左右融合标定、OM runner、模型、MR20 配置、依赖和调试端口，并严格按左后右顺序读取首帧，不会同时 STREAMON。正式 `ss928_om` 模式只要求 `cv2/numpy/dbus/gi`，不会强制安装 `torch/ultralytics/lap`；只有 legacy 视觉或显式选择 Ultralytics snapshot backend 才检查对应 Python 推理栈。旧单目视觉标定只在 `legacy_dual_vision` 中检查。预检不能替代关联准确率和 30 分钟稳定性测试。

## 5. 旧双视觉回归

```sh
sudo sh dual-vision-test.sh /path/left.mp4 /path/right.mp4 /etc/smartbag/config.json
```

该命令只用于 `legacy_dual_vision` 回归，仍启动两个独立 detector，不代表新雷达主模式。新融合链使用 `radar_vision_fusion/fusion_replay.py` 回放 RadarScan 和 ClassificationFrame JSONL。

## 6. 正式启动和日志

```sh
sudo systemctl enable --now smartbag.target
sh status.sh
sh logs.sh -f
journalctl -u smartbag-alert.service -f
```

`smartbag-alert.service` 在新模式中启动双 MR20 worker、一个交替快照分类器、当前图片关联、共享 RiskModel 和每轨迹 0.5 秒中位数窗口，不启动两条旧 detector 命令。视觉失败或映射过期时保留雷达并使用 unknown；每张新图都会替换本侧全部车型映射，不使用长期绑定。事件过期、level=0、SIGTERM、异常和 `ExecStopPost` safe-off 都会清振/灯。

`smartbag.target` 默认只必需 alert；旧 `smartbag-video.service` 不再默认启动，避免与融合调试 API 冲突。WS73、MT5710 connectivity 和 temperature 仍按条件启动。

## 7. 融合调试接口

```sh
curl http://127.0.0.1:8080/api/v1/fusion/status
curl http://127.0.0.1:8080/api/v1/fusion/targets
curl -o left.jpg http://127.0.0.1:8080/api/v1/fusion/left/snapshot.jpg
curl -o right.jpg http://127.0.0.1:8080/api/v1/fusion/right/snapshot.jpg
curl http://127.0.0.1:8080/api/v1/settings/runtime
curl -X PATCH -H 'Content-Type: application/json' -d '{"risk":{"warning_sensitivity":1.2}}' http://127.0.0.1:8080/api/v1/settings/runtime
curl 'http://127.0.0.1:8080/api/v1/alerts/history?limit=20&min_level=3'
```

快照会显示 YOLO bbox、扩展框、雷达投影容差区间、重合段、radar target ID、matched/unknown/ambiguous、association cost、中位数和最终 haptic 等级。HTTP 还提供运行参数白名单 PATCH/reset 和三级/四级事件详情/图片；这些接口不参与风险计算，也不提供连续 MJPEG。访问令牌可在 fusion 配置中设置；正式公网仍需 HTTPS、认证和防火墙。

## 8. 微信小程序

在微信开发者工具导入 `06_software/mobile/ssminiprogram`。“系统参数”页实时读写安装参数、关联范围、灵敏度和车型权重；“交通危险事件”页读取板端三级/四级事件并把同侧 JPEG 保存到手机本地。按 `event_id` 去重，离线时先存 BLE 元数据，之后可重试图片；CloudBase 上传失败不会影响本地记录或板端保存。

现有“**双摄实时画面**”页面使用旧 `smartbag-video.service` 的连续画面 API，只适用于手动启动的 legacy gateway。新融合调试快照使用 `/api/v1/fusion/...`，默认不启动旧 gateway，也不会同时打开两个摄像头。手机设置通过 `wx.setStorageSync` 保存，不写死设备 IP。

开发者工具可临时关闭域名/TLS 校验。正式真机必须使用实际 AppID，并根据微信当前规则验证局域网 IP、合法域名和 HTTPS；游客 AppID 或调试模式成功不代表发布版成功。手机与板端必须处于可互访网络，AP 客户端隔离需要关闭。BLE 仍只传告警、GNSS、IMU 和 `SYS STATUS`。

## 9. 性能降级顺序

先查看 `/api/v1/fusion/status`，记录每侧 `capture_latency_ms`、`inference_latency_ms`、快照年龄、模型错误、雷达频率和 unknown 比例，再逐项调整：

1. 将 `initial_warmup_frames` 从 2 降到 1，并确认首次快照不是旧图或黑帧。
2. 若 `switch_interval_ms` 持续 overrun，适当增加 `target_switch_interval_s`；这不会降低雷达扫描频率。
3. 保持 `capture_frames=1`，不要建立旧帧队列。
4. 在真实车辆数据上调 `confidence`、投影区间、bbox 扩展和歧义间隔，不以强行匹配换取表面命中率。
5. 若 OM 延迟异常，检查 runner stderr、模型 I/O 合约和 NPU 温度；不要自动退回两个 Torch 进程。

2026-07-16 历史镜像只有约 952 MiB 内存且缺少视觉依赖；部署时必须重新检查当前镜像。PC 的 Ultralytics/BoT-SORT profile 仍在视觉 README 中，仅用于纯视觉回归，不是本模式性能参数。

`vision/ss928_backend` 支持持久 runner：模型初始化一次，逐快照读取 NV12 并输出 detections JSON。仓库外本地已找到一个候选车辆 OM，但它是 RGB_PLANAR AIPP，不能直接喂给当前 NV12 runner；模型和 runner 合约统一前，状态仍是 BLOCKED。新模式不把 detections 接入 BoT-SORT，而是仅与持续雷达轨迹做当前图片的一一关联。

## 10. 停止和卸载

```sh
sudo sh stop-all.sh
sudo sh uninstall.sh
```

卸载不删除 `/etc/smartbag` 和 `/var/lib/smartbag`。升级使用 `upgrade.sh` 和 `migrate_config.py` 保留本地值；需要切换 profile 时先备份配置，再运行 `apply_hardware_profile.py`。BMI270 blob、模型、真实标定、设备身份和 secret 均由用户合法提供。
