# Project Log

## 2026-07-19

- 从基线 `06c6cfd1dc11a0f92c54ce8aad5252d554ececa5` 创建独立实验分支 `agent/alternating-dual-camera`，未修改正式集成分支。
- 基于归档中的标准 V4L2 UVC sample 实现 Python ctypes mmap 采集器，保留两个已初始化 fd，但通过严格状态机保证任何时刻最多一路 STREAMON；未使用或伪造 SS928 私有摄像头/NPU API。
- 在真实 SS928 上完成 640x480/320x240、请求 5/10 FPS 的四组 2 分钟 A 测试和 30 秒 B 缓存预览。总计 989 次 A 切换全部成功、无 ENOSPC；实际均协商为 MJPEG 30 FPS，最大盲区 539.016 ms。
- 额外请求 1680x1050@10 的 30 秒交替测试实际协商为 1920x1080@30，61/61 次切换成功、无 ENOSPC；该离散分辨率请求没有成功，且 RSS 峰值升至 54.836 MiB。
- 完成 C/D 代码和无硬件测试：共享模型只初始化一次，左右 tracker/risk/context 独立；多帧稳定器增加 monotonic 时间确认指标，controller 区分状态变化与 PWM 心跳，detector 退出/陈旧观测会清振。
- 本机真实 Ultralytics 冒烟测试使用一个 YOLO 实例和两个独立 BoT-SORT 实例，左侧连续帧保持本侧 ID，右侧使用独立 tracker 状态。板端因缺少 cv2/torch/ultralytics/lap 尚未运行 C，PWM/BLE 也未做实物 D 验证。
- 原始板端 session 已下载到本地 `08_media/alternating_camera_runs/` 并保持 Git 忽略；仓库只记录匿名化摘要、分析、脚本、源代码和测试。
- 最终本地回归为 224 项 Python 测试和 4 个小程序测试文件；板端运行交替采集 12 项、controller 9 项、compileall、部署 shell `sh -n` 和 JSON 解析。板端缺少 cv2，依赖该模块的风险 overlay 测试按未执行记录，没有伪报通过。

## 2026-07-16

- 通过 USB-UART 在真实 SS928 板上完成只读审计：确认 Ubuntu 22.04.1/aarch64、SDK V2.0.2.2、952 MiB 内存，以及 `/dev/video0`/`video2` 两路 UVC。两台相机序列号相同且共用同一 USB 2.0 hub；单路底层 MJPEG 短测约 8.42/7.46 FPS，双路 640x480/320x240 均出现一侧 `ENOSPC`。板上缺少 cv2/torch/ultralytics/lap，故未宣称视觉检测已在板端运行。
- 审计本地 `10_archive/ss928` 的产品规格书、UVC sample、MPP VENC/RTSP、OpenCV/Python、Wi-Fi/BlueZ 和 NPU/`.om` 资料，形成 `02_research/dual-usb-camera-board-analysis.md`；区分“归档存在”与“当前板上已验证”。
- 默认架构改为左右固定双 USB 摄像头、两个独立 detector、统一 Controller、双路 LAN video gateway 和统一 BLE。每侧 tracker、风险模型、stabilizer、限流和 risk CSV 独立。
- 完成 latest-frame 单所有者采集、按需 JPEG、snapshot/MJPEG、离线状态、有限重连、子进程有限重启和资源状态；没有实现或伪造 SS928 NPU 后端。
- 完成微信小程序双摄页、自动视觉告警历史和真实 SYS 状态，移除首页假在线/假电量信息。
- 默认 systemd 只启动 `smartbag-alert.service` 与 `smartbag-video.service`；IMX347/VO 和单摄诊断 unit 不进入 `smartbag.target`。
- 本地验证：视觉 145 项、四个板端模块 24 项、跨模块 26 项、USB 录像工具 8 项，共 203 项 Python 测试通过；小程序 4 个测试文件和全部静态检查通过。真实板端只完成 UVC 底层诊断，视觉 detector、双路流和手机仍未跑通，不记录推理性能估计。

## 2026-07-15

- 完成 `sanda-tt/ss928` 的板端功能审计与选择性迁移，固定来源提交为 `d7e10fd06dc553f94d2db3a3d19987ec8648f7dc`，未修改来源仓库。
- 当前正式路线明确为纯视觉避障；雷达实验从活动目录移除，历史保留在 Git。
- 建立 vision -> stabilized haptic JSONL -> controller -> PWM/optional audio 事件链，并统一 GNSS、BMI270、fall event 和单一 BLE NUS。
- 默认部署使用一个摄像头和一个 detector；双摄仅作为兼容配置，SS928 NPU/OM 后端待真实 SDK/API 验证。
- 新增统一 `/root/smartbag` 部署包、systemd 服务、硬件资源文档和集成测试。
- 本地验证 181 项 Python 测试与 8 项小程序断言通过，`compileall`、JSON 解析和 9 个 shell 脚本语法检查通过；真实板端外设仍待验证。

## 2026-06-06

- Vision prototype updated for review feedback: native-scale preview by default, 1920x1080 live input request, YOLO imgsz 640, confidence 0.15, max detections 1000, and default target classes set to car/bicycle/motorcycle/bus/truck.
- Distance and speed calibration default changed to 1.1m camera height for chest-mounted testing. Display scaling is now preview-only and does not reduce the frame used by YOLO.
- Live FFmpeg camera input keeps the newest decoded frame to reduce accumulated latency. If the camera delivers only about 7fps at all requested resolutions, the limiting factor is camera exposure/driver delivery rather than YOLO.
- Slow-preview regression traced to the sensitive live profile (`conf=0.10`, `imgsz=960`) being used as the default and to video display adding source-FPS wait after processing. Default restored to `conf=0.15`, `imgsz=640`, and display wait is now 1ms.
- Raw USB Camera read benchmark on 2026-06-06 showed about 5-6 FPS at 1920x1080, 1280x720, and 640x480 with YOLO disabled, indicating the current bottleneck is camera exposure/driver delivery.
- Requirement corrected: high sensitivity must remain the default. Vision prototype now keeps `conf=0.10` and `imgsz=960`, while latency work is limited to dropping stale frames, using low FFmpeg/DirectShow buffering, and keeping display wait at 1ms.
- Recorded-video preview latency traced to sequentially processing every source frame. Default video preview now skips stale frames based on wall-clock video position; `--video-every-frame --no-display` remains available for full offline export.
- Follow-up profiling on `usbcam_20260605_183928.mp4` showed H.264 random frame seeking at only about 3.35 FPS while sequential decode exceeds 100 FPS. Video preview now uses a background sequential decoder with latest-frame delivery instead of `CAP_PROP_POS_FRAMES` seeking.
- Distance/speed algorithm upgraded for 120-degree wide-angle USB camera: default FOV is now diagonal 120 degrees, default chest-mount pitch is 5 degrees, and distance uses fused ground-plane plus vehicle-size estimation. Track speed now uses smoothed distance history with spike rejection instead of adjacent-frame differencing.
- Added field calibration controls: `--distance-mode`, `--size-weight`, `--distance-scale`, `--speed-scale`, `--speed-window`, `--distance-smoothing`, `--max-speed`, plus optional `--enhance auto/clahe/off` for low-light contrast.
- Added first risk warning overlay model: per-target `RiskScore`, TTC, CPA, warning level, and color-coded boxes. Warning colors are yellow, orange-yellow, orange-red, and red for attention/caution/danger/emergency. Model combines TTC, closest-point distance, required deceleration, closing speed, lateral cut-in, uncertainty, and vehicle type severity.

## 2026-05-13

- 重建嵌赛长期协作项目目录。
- 当前目录骨架用于分类保存规则、需求、调研、设计、硬件、固件、软件、测试、演示交付物和归档材料。
- 下一步：确认比赛方向、题目/赛道、目标硬件平台、团队分工和近期里程碑。
- 初步确定项目方向为智能背包，主控平台为海思 SS928。
- 核心功能暂定为智能避障提醒和智能背包物品检测，技术路径分别侧重雷达 SLAM 与视觉大模型。
- 附加功能候选包括健康姿势检测、防丢提醒、异常开包提醒和移动端状态同步。
- 生成报名用推荐项目名称：智行护航：基于海思 SS928 的多模态感知智能背包。

## 2026-05-28

- 雷达避障方案第一版调整为 PC 端毫米波雷达前向扇区测试，不做 SLAM，不做 360° 全向拼接。
- 依据 archive 中的雷达资料确认模块为 `MS60-3015S80M4-3V3-B-NLS-1T2R-S7136H`，水平视角 `±40°`，默认 UART `921600`，BSD 上报最多 8 个目标。
- 创建 `06_software/radar_visualizer`，实现雷达协议解析、目标风险判断、实时扇形 GUI 可视化和 demo 模式。
- 当前版本用于电脑 USB-TTL 初测；震动模块和 SS928 板端接入后续再做。

## 2026-06-05

- 视觉避障路线先做 PC 端实时原型，使用已识别的 `USB Camera` 采集视频数据，暂不进入 SS928 板端部署。
- 创建 `06_software/usb_camera_recorder`，实现 Windows GUI 录像工具，可点击开始/停止录制并保存 MP4。
- 录像默认请求参数为 `USB Camera`、`2560x1440`、`30fps`、H.264 MP4，默认保存目录为 `08_media/camera_data`。
- 已用 PyInstaller 打包单文件程序：`06_software/usb_camera_recorder/dist_onefile/USB Camera Recorder.exe`。
- 实测 DirectShow 模式表显示该摄像头支持 MJPEG `2560x1440@30fps`，但当前环境 8 秒采集约 60 帧，实际约 `7.5fps`；后续采集 30fps 数据时需要增加光照、检查摄像头曝光设置，或临时降低分辨率验证。
- 录像工具增加开始录制时自动打开预览窗口：FFmpeg 打开摄像头一次，同时保存 MP4 并通过 MJPEG 管道喂给 FFplay 预览，避免摄像头被两个程序重复占用。
- 修复预览模糊和延迟问题：原方案把预览缩放到 960px 并重新编码为 MJPEG，导致画质软且延迟高；新方案直接复制摄像头原始 MJPEG 帧给 FFplay 预览，并把录制质量从 CRF 20 提高到 CRF 18。实测 `2560x1440`、约 `30fps`。
- 创建 `06_software/vision_obstacle_tracker` PC 端视觉原型：支持 `--source camera` 读取 USB Camera，也支持 `--source video --video <mp4>` 导入录像测试；使用 Ultralytics YOLO + ByteTrack 做检测/跟踪，OpenCV 显示检测框、track ID、类别、置信度、单目估算距离和 `vx/vz` 速度向量。
- 当前视觉测距测速使用“相机高度 + 俯仰角 + 水平视场角 + 平地假设”的单目近似，主要用于算法链路验证；后续需要用标定数据修正，最终高可信距离/速度应融合毫米波雷达。
- 已安装依赖 `opencv-python`、`ultralytics`、`torch CPU`、`lap`；实测视频入口和摄像头入口均可处理限定帧数并退出。
- 视觉原型性能调优：`2560x1440` 在 OpenCV 摄像头读取阶段即被限制到约 `1.6fps`，不是 YOLO 本身瓶颈；改为默认 FFmpeg MJPEG 管道读取 `1280x720`，YOLO `imgsz=416`，实测约 `18fps`，兼顾识别细节和实时性。若追求更高帧率可改 `640x480`。
- 修复 1080p 实时预览延迟：原 FFmpeg 摄像头读取按 FIFO 顺序处理 MJPEG 帧，YOLO 低于摄像头帧率时会积压旧帧；改为后台线程持续读取并只保留最新帧，主循环跳过过期帧。`1920x1080 + imgsz=416` 实测约 `17fps`，但延迟不再随运行时间累积。
