# Project Log

## 2026-07-21

- 按现场观察需求将板端双摄网页改为一个主画面，每 1 秒轮换显示左、右缓存的检测快照；两侧状态信息继续同时显示。显示轮换完全位于 HTTP 页面层，未修改相机 STREAMON/OFF 调度、每侧 NPU 推理、tracker、风险模型或 haptic 输出。
- 恢复板端以太网 SSH 后完成正式 NPU 短测。ACL 元数据确认板载 `yolov8n.om` 为逻辑 `1x640x640x3 UINT8`、物理 614400-byte 静态 AIPP NV12 输入；修正此前错误的 RGB byte-size 假设，并保留普通 RGB CHW/HWC 模型兼容。
- 板端 84.425 秒完整链完成 99/99 次左右切换、99 帧 NPU/tracking/risk/overlay；NPU execute 约 25.66 ms，detector 总耗时约 81.1 ms，CPU 平均 14.403%，RSS 平均 115.916 MiB。E2E p95/max 为 1219.665/1272.578 ms，短测尚未达到 1200 ms max 门限。
- 左右 raw/overlay HTTP 均可读取，但两台相机当前连续输出近乎全黑 JPEG；50 帧持续采样仍黑，且正确 capture 节点和 V4L2 控制已核对。因此记录为 NPU 链功能通过、实景目标命中阻塞，不宣称检测框和风险实景验收通过。
- 通过离线 aarch64 wheel 安装 NumPy 1.26.4 与 opencv-python-headless 4.10.0.84，只运行摄像头/NPU。发现并停止板上残留、反复访问未连接 TM6605/I2C 的旧 `smartbag-alert.service`，未启动 PWM、BLE、GNSS、IMU、雷达或音频。
- 将已测试代码提交 `65364a5b3bd6a06e9ad53687d1942b2ec90bb391` 安装到 `/root/smartbag/releases/65364a5`，以软链接提供统一 `vision` 和 `python-packages` 路径，并链接板上合法模型。生产目录 compileall 和模型 metadata smoke test 通过；没有启用新的 systemd 服务，旧 alert unit 已禁用。
- 本地仓库回归更新为 296 项 Python 测试（295 通过、1 项 Linux-only 跳过）；新增静态 AIPP NV12 格式、Y/UV 排列、字节数和 fake NPU 输入测试。
- 将此前单图 ModelZoo harness 收敛为正式长驻后端：`libsmartbag_ss928_acl.so` 只在进程启动时初始化 ACL、加载 `yolov8n.om` 并分配输入/输出 dataset；Python 通过 ctypes 传内存 tensor，避免临时文件和逐帧模型加载。
- 固定并校验当前模型契约：ACL 图像 tensor（普通 RGB 或静态 AIPP NV12）、COCO 80 类、单个 FP32 `1x84x8400` 输出；契约不匹配时拒绝启动。当前 ACL 镜像的 `aclFinalize()` 退出异常被限定在原生 adapter 内，正常释放模型、dataset 和 buffer 后由进程退出回收 ACL 全局状态。
- SS928 输出已经接入原有 tracking、单目测距、速度、Future Conflict Gate、多帧 stabilizer、haptic JSONL、CSV 和 overlay；交替双摄共享一个模型，左右 IoU tracker、StableTrackId、TrackState 和 RiskModel 相互独立。
- 本地已完成 adapter ARM64 交叉编译和针对预处理、输出解码、ROI 坐标恢复、独立 tracking、controller 参数透传的测试。实板连续 NPU/overlay 状态需在板端网络或串口恢复后补测，不把本地结果记为 BOARD TESTED。
- 最终回归为 296 项 Python 测试（295 通过、1 项 Linux-only 跳过）、6 个小程序测试文件、24 个 JS 语法、22 个 tracked JSON 和 39 个 shell 语法；compileall、硬件刷新仓库策略与 diff whitespace 通过。ARM64 adapter SHA256 为 `00a496a6576f2f8473274878535715dfe47697b5f33692c4203f5ec913fdbe9d`。

## 2026-07-20

- 将纯摄像头网页从三条并行 MJPEG 调整为一条顶部低延迟交替流和每秒左右缓存快照，减少重复传输与浏览器解码；在当前两只摄像头上验证 300 ms 时间片、0 预热丢帧、每片 4 帧，80 帧全部解码正常，左右各约 4.85 FPS，交替总流约 8.52 FPS，p95/最大帧间隔约 311/340 ms。硬件 STREAMON/OFF 仍造成约 0.3 秒周期停顿，未伪装为稳定同步双摄。
- 继续诊断板端网页卡顿：标称千兆链路的小包延迟约 1–3 ms，但板端累计大量 TCP retransmit，PC 读取 JPEG 仅约 0.7 Mbps；将实际 `eth1` 临时限制为 100M 全双工后达到 27.3 Mbps。新增无积压的低延迟交替流，用左右最新帧把实测更新提高到约 7.63 FPS、最长无帧间隔降至约 400 ms；剩余波动来自 STREAMON 首帧等待和突发出帧，纯采集仍不声称具备检测 overlay。
- 将板端浏览器预览从实际 1920x1080 降至原生 1280x720，并用 1 帧预热/每片 6 帧平衡切换开销，左右 capture FPS 从约 4.15 提高至约 5.8–6.0；5 秒左右端点各收到 11 个 MJPEG 分段，无流切换错误。页面随后增加 overlay 禁用和断线自动重连。
- 通过板端 `eth1` 有线地址完成 PC 浏览器双摄预览，定位并修复两层黑屏原因：纯采集没有 overlay 但首页默认请求 overlay，以及 UVC 每次重启流后 sequence 重复导致 MJPEG 错误去重。实板浏览器最终确认左右图像 `naturalWidth/naturalHeight=1920/1080`，未启用 YOLO、PWM 或其他外设。
- 从 `agent/sanda-hardware-refresh@0fbe815e8a7f51fc32e925bce086be99ceca84a9` 创建 `agent/rev2-autonomous-board-runtime`，不修改基线分支。
- 将 Rev2 震动、灯光和音频改为有界持续状态；新增本地自主启动 target、固定 venv、模型门禁、硬件等待、安全关断、boot self-test 和分阶段板端验证编排。
- 默认配置切换为 `alternating_single_model`，controller 统一监督子进程并独占 BLE；核心 unit 不依赖 `network-online.target`，Cloud uploader 保持可选。
- 小程序本地预警历史扩展为 100 条完整记录，支持 BLE/Cloud 来源、clear 原因、haptic/light/audio 实际决策和重启恢复。
- 用户随后允许在只连接两台摄像头的开发板上做非生产暂存和摄像头识别测试。提交 `a660901` 已通过 USB-UART 暂存到 `/root/smartbag-staging/a660901` 并校验 SHA-256；未执行 `install.sh`、systemd enable、执行器或其他传感器测试。
- 双 UVC 请求 `1680x1050 MJPEG @10` 时实际得到 1920x1080；10/10 次交替、左右各 20 帧均成功，无流错误，最大 capture-only 盲区 545.945 ms。重启后 `/dev/video0` 与 `/dev/video2` 的物理口映射互换，确认正式配置必须使用稳定路径/身份映射。
- 左右快照都进入板上 `yolov8n.om` 并生成张量/检测文本，NPU 执行约 25.44 ms；现场无交通目标，`conf>=0.25` 无命中。临时 ModelZoo harness 在修正模型卸载顺序后仍于 `EnvDeinit()` 异常，正式 `Ss928OmBackend`、实时跟踪/风险/overlay 继续标记 BLOCKED。
- 新增 USB-UART 双向单文件传输工具，支持 `.part` 原子替换和 PC/板端 SHA-256 交叉校验；原始图片、模型和临时二进制只放在 Git 忽略的 `08_media`。
- 本地最终回归：280 项 Python 测试中 279 项通过、1 项 Linux-only `fcntl` 测试跳过；6 个小程序 JavaScript 测试文件、24 个 JS 语法、38 个 shell 语法、22 个跟踪 JSON、compileall、safe-off dry-run 和仓库策略通过。
- 从 `agent/alternating-dual-camera@a5f6d815b924129fca03c8392912f31b843da636` 创建 `agent/sanda-hardware-refresh`；来源固定为 `sanda-tt/ss928@970351c84a12f3219e7910ee488ac5ff579d6f98`，未修改来源仓库和现有 PR #2。
- 通过 GitHub Compare/Tree/Contents API 审计上游 19 个新增提交和 28,904 项树记录；本机 partial clone fetch 因 443 连接重置失败，审计清单保留 blob SHA、许可状态和迁移决策。
- 重实现统一 I2C mux、双 TM6605、双灯、MR20、来源融合、输出策略和 Cloud 安全链路；未复制上游 SDK、模型、PDF、二进制或许可不明运行代码。
- 本地完成 267 项 Python、6 个 JS 测试文件、24 个 JS 语法、mock/replay/配置/脚本检查；Windows 上仅跳过 Linux `fcntl` 进程锁测试。收尾时板端未枚举为 USB 串口/网卡且 SSH 不可达，真实板端项保持 BLOCKED。

## 2026-07-19

- 从基线 `06c6cfd1dc11a0f92c54ce8aad5252d554ececa5` 创建独立实验分支 `agent/alternating-dual-camera`，未修改正式集成分支。
- 完成交替视觉 E2E 管线：每片默认只推理最新 1 帧、无积压队列，记录 capture-only 与完整 E2E 观测间隔、跨侧延迟和解码/推理/tracker/风险/overlay/JPEG 全阶段时间戳。
- 风险稳定器增加跨不同 `slice_id` 的 CAUTION/DANGER/EMERGENCY 确认；tracker 支持 `effective_side` 时间尺度；单帧跳变抑制、跨 slice 确认和 fast path 改为真实计数。
- 交替 detector 内置左右 raw/overlay gateway、状态 API 和双画面浏览器页；小程序改为 completion-driven refresh、单 in-flight、生命周期停止、指数退避和单侧聚焦模式。
- 增加单侧相机 close/reopen/remap 状态机与详细恢复事件；增加左右安装外参、背包坐标变换、production 标定检查器、部署 preflight、session 清理 timer 和 GitHub Actions。
- 基于归档中的标准 V4L2 UVC sample 实现 Python ctypes mmap 采集器，保留两个已初始化 fd，但通过严格状态机保证任何时刻最多一路 STREAMON；未使用或伪造 SS928 私有摄像头/NPU API。
- 在真实 SS928 上完成 640x480/320x240、请求 5/10 FPS 的四组 2 分钟 A 测试和 30 秒 B 缓存预览。总计 989 次 A 切换全部成功、无 ENOSPC；实际均协商为 MJPEG 30 FPS，最大盲区 539.016 ms。
- 额外请求 1680x1050@10 的 30 秒交替测试实际协商为 1920x1080@30，61/61 次切换成功、无 ENOSPC；该离散分辨率请求没有成功，且 RSS 峰值升至 54.836 MiB。
- 完成 C/D 代码和无硬件测试：共享模型只初始化一次，左右 tracker/risk/context 独立；多帧稳定器增加 monotonic 时间确认指标，controller 区分状态变化与 PWM 心跳，detector 退出/陈旧观测会清振。
- 本机真实 Ultralytics 冒烟测试使用一个 YOLO 实例和两个独立 BoT-SORT 实例，左侧连续帧保持本侧 ID，右侧使用独立 tracker 状态。板端因缺少 cv2/torch/ultralytics/lap 尚未运行 C，PWM/BLE 也未做实物 D 验证。
- 原始板端 session 已下载到本地 `08_media/alternating_camera_runs/` 并保持 Git 忽略；仓库只记录匿名化摘要、分析、脚本、源代码和测试。
- 完成 1800.247 秒纯采集长测：3620/3620 切换、左右各 7240 帧、无 ENOSPC/首帧超时，capture-only 最大盲区 580.264 ms。原始 tar 仅保存于 `08_media`，SHA256 为 `7F076DD52647FD97C73581B7D6F8BE7408985061FCF1E86A542479E010F0A523`。
- 完成左右 USB 设备的 sysfs 逻辑 unbind/rebind，约 3 秒恢复且另一侧继续；发现并修正 reconnect 汇总未按侧累计的问题。该测试不等于人工物理拔插。
- 根据长测 RSS 增长，把 switch/performance/E2E/阶段计时内存历史改为有界 deque，精确总数、均值、峰值单独累计；修复后的第二次 30 分钟实板复验仍待执行。
- 当前本地回归为 229 项 Python 测试和 4 个小程序测试文件；compileall、16 个跟踪 JSON、部署 shell `sh -n`、CI YAML、仓库策略和 `git diff --check` 通过。板端缺少完整视觉依赖，风险 overlay/PWM/BLE 真机测试仍按 BLOCKED 记录，没有伪报通过。

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
