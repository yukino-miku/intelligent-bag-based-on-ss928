# Project Log

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
