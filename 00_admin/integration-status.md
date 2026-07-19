# SS928 板端整合状态

## 已完成

- 新增默认关闭的 `alternating_single_model` 回退模式：原生 V4L2 单 active side、单次模型加载、左右独立 tracker/risk/标定/CSV、稳定 haptic 风险优先调度和 session 报告。
- Controller 已区分 `state_change` 与 `heartbeat`；切换相机不把未观测侧当成 SAFE，heartbeat 不进入 BLE 历史，stale observation 或单进程 detector 退出会清除对应/全部 PWM 状态。
- 正式 systemd 使用左右固定双 USB detector；配置拒绝同一真实设备或相同 stream port，跨侧告警被 Controller 拒绝。
- 每个 detector 是相机唯一所有者，使用容量 1 latest-frame buffer、有限断流重连、独立 tracker/RiskModel/stabilizer/CSV 和稳定 haptic JSONL。
- 左右 PWM 独立；单侧 level=0、超时或 detector 退出只清对应侧，子进程有限退避重启，另一侧继续。
- 双路 snapshot/MJPEG、聚合状态、浏览器调试页和按需 JPEG；BLE 不传视频。
- 微信小程序双摄页、地址 storage、raw/overlay、暂停/重连、左右自动告警和真实 SYS 状态。
- GNSS/BMI 默认不注册 BLE；统一设备名为 `SS928-SmartBag`。
- 双标定模板、依赖/相机/preflight/stream/模拟双视频脚本和部署文档已齐全。
- 本地 203 项 Python 测试、4 个小程序测试文件和 compileall/JSON/JS/shell/diff 检查通过。

## 真实开发板已验证（更新至 2026-07-19）

- USB-UART 登录确认 SS928V100、Ubuntu 22.04.1/aarch64、Linux 4.19.90、4 CPU；当前总内存仅 952 MiB、无 swap。
- 两台 `0bda:3035` UVC 相机分别枚举为 `/dev/video0`、`/dev/video2`，但序列号相同导致 by-id 冲突，只能用不同 by-path 固定物理口。
- 两台相机当前共同挂在 `10320000.xhci_1` 的 USB 2.0 hub 下。标准库 V4L2 mmap 单路短测约 8.42/7.46 FPS；双路 640x480 和 320x240 均有一侧 `ENOSPC`，当前接法未通过双摄验收。
- 当前镜像缺少 `cv2/torch/ultralytics/lap` 及 V4L2/FFmpeg/GStreamer 工具，板端视觉和推流尚未启动；未修改现有 systemd 服务。
- 原生 `v4l2_stream_toggle` A1-A4 每组约 2 分钟，总计 989 次切换全部成功，无 ENOSPC/首帧超时；p95 切换 273.726-278.018 ms，最大单侧盲区 539.016 ms，左右有效约 4.08-4.13 FPS。
- B 阶段缓存双画面 status、左右 snapshot 和浏览器页均返回 HTTP 200；gateway 不重新打开摄像头，退出后 `/dev/video0`、`/dev/video2` 均无占用。
- 5/10 FPS 请求都被协商为 30 FPS，温度 sysfs 节点仍未确认。A 尚未完成连续 30 分钟，因此实验模式不满足默认启用条件。

## 仍需真实硬件验证

- 将一台相机移到另一 USB 根控制器，重新确定两个 by-path，并完成双摄持续 FPS、掉线重连和总线带宽测试。
- 通过联网 apt 或经过 ABI 验证的离线 aarch64 包补齐 OpenCV/torch/ultralytics/lap，再验证模型加载。
- `board_dual_balanced` 双 detector 的 capture/inference/stream FPS、CPU、内存、最高温度和 30 分钟以上稳定性；当前只有未解码的短时 UVC 数据。
- `alternating_single_model` C 阶段的板端模型加载、双侧检测、真实推理盲区、RSS/CPU/温度，以及 D 阶段左右 PWM、heartbeat、stale clear 和 BLE 历史。
- 左右独立相机内参、畸变、高度、pitch、朝向和风险日志实景校准。
- PWM sysfs 编号、四路物理方向、电机驱动供电、单侧退出清振和紧急停止。
- BlueZ NUS、自动 alert、GNSS/IMU/SYS 往返；手机真机 snapshot、局域网/HTTPS/合法域名限制。
- DX-GP21 UART4、BMI270 IIO/I2C、MAX98357；音频默认关闭。

## 未完成

- `Ss928OmBackend` 没有与现有 Python detector、BoT-SORT 和风险链兼容的真实厂商 API。归档仅证明存在 ATC、`.om` 和 C/C++ sample；OpenVINO 不是 SS928 NPU。
- MPP VENC/RTSP 尚未接入当前 UVC detector 帧。当前交付是 CPU JPEG snapshot/MJPEG 基线，不宣称硬件 H.264/H.265 已完成。
- 微信小程序真机和正式 AppID/HTTPS/合法域名尚未验证；浏览器页是当前独立板端视频验收入口。
