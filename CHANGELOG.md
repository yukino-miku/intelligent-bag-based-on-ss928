# 更新记录

## 2026-07-21

- 修正 SS928 板载模型输入格式：ACL 元数据的逻辑维度虽然为 `1x640x640x3 UINT8`，实际静态 AIPP 输入仅 614400 bytes，必须提交 NV12。后端现按 tensor byte size 自动识别 NV12，完成 BGR letterbox、I420 到 NV12 UV 交错转换，并保留普通 RGB CHW/HWC 路径。
- 新增静态 AIPP NV12 元数据、Y/UV 排列、字节数和 fake NPU 端到端测试；仓库级回归为 296 项 Python 测试（295 通过、1 项 Linux-only 跳过）。
- SS928 短测完成 99/99 次双摄交替和 99 帧完整 NPU/tracking/risk/overlay：NPU execute 约 25.66 ms，detector 总耗时约 81.1 ms，CPU 平均 14.403%，RSS 平均 115.916 MiB。完整 E2E max 1272.578 ms，略高于 1200 ms 门限，仍需调参和长测。
- 当前两路 UVC 原始 JPEG 连续采样仍近乎全黑；HTTP raw/overlay 和 NPU 链正常，但没有实景目标命中证据。验收状态明确拆为 `BOARD FUNCTIONAL PASS` 与 `CAMERA IMAGE BLOCKED`，不把黑帧推理记为检测准确性通过。
- 实现正式 `Ss928OmBackend`：新增常驻 `.om` 模型的 SS928 ACL C ABI，USB BGR 帧直接在内存中完成 letterbox，并按模型契约转换为 RGB tensor 或静态 AIPP NV12，再执行 NPU、`1x84x8400 FP32` 解码、类别过滤、class-aware NMS 和原图坐标恢复，不再逐帧写临时图片。
- NPU 检测结果接入现有稳定 ID、距离/速度估计、Future Conflict Gate、多帧风险稳定、visual/haptic 输出、risk CSV 和 overlay；单摄使用轻量 IoU tracker，交替双摄保持左右 tracker/risk/标定完全独立且只加载一个模型。
- 双摄 performance CSV 新增 preprocess、NPU execute 和 postprocess 分项；部署配置默认选择 `yolov8n.om` 和 `ss928_om`，preflight 根据后端检查依赖，NPU 路径不要求 torch/Ultralytics/lap。
- 新增 ARM64 adapter 构建脚本、模型 tensor 契约检查、无 Ultralytics 单元测试和部署说明。代码与交叉编译通过不等同于实板连续目标检测通过，真实 overlay、目标命中、30 分钟稳定性和温度仍需板端验收。
- 最终本地回归为 296 项 Python 测试（295 通过、1 项 Linux-only 跳过），并通过 6 个小程序测试文件、24 个 JS 语法、22 个 tracked JSON、39 个 shell 语法、compileall、仓库策略和 whitespace 检查。

## 2026-07-20

- 优化 SS928 交替预览稳定性：网页默认从三条重复 MJPEG 改为一条顶部实时交替流加每秒左右缓存快照；实板验证 `640x480@30`、300 ms 时间片、0 预热丢帧、每片 4 帧时，80 帧解码无黑帧或损坏，左右各约 4.85 FPS，交替总流约 8.52 FPS，最大帧间隔约 340 ms。
- 增加 `/api/v1/alternating/mjpeg` 低延迟交替流和网页主画面，直接转发左右最新帧且不回放旧帧；保留左右缓存窗口。实板发现现场千兆协商伴随大量 TCP 重传，临时限制为 100M 全双工后 JPEG 吞吐由约 0.7 Mbps 升至 27.3 Mbps，交替流达到约 7.63 FPS、最长帧间隔约 400 ms；剩余抖动来自共享 USB 2.0 下每次约 240–300 ms 的 STREAMOFF/STREAMON 切换。
- 增加 SS928 720p 交替预览实测配置：1280x720、30 FPS 请求、400 ms 时间片、1 帧预热、每片 6 帧，左右 capture FPS 约 5.8–6.0；明确网页是并排 live/cached 更新而非整页左右闪切。
- 纯摄像头页面在 overlay 不可用时禁用“检测画面”切换，并为左右 MJPEG 增加 1 秒断线重连，避免误入空 overlay 或网关重启后保持黑屏。
- 修复 SS928 纯摄像头交替预览黑屏：`stream_only` 首页在没有左右 overlay 时自动使用 raw；MJPEG 去重不再仅依赖会在每次 STREAMON 后重复的 V4L2 sequence，而是同时比较采集和发布时间。
- 实板回归确认左右 raw 流均可被浏览器解码为 1920x1080，3 秒测试收到 3 个连续 MJPEG 分段，左右在线且 STREAMON/STREAMOFF 失败均为 0；新增 3 项网关测试，交替采集测试文件共 22 项通过。
- 新建 `agent/rev2-autonomous-board-runtime`：默认运行改为 `smartbag.target -> smartbag-controller.service`，controller 内部监督单模型双 UVC 交替采集、GNSS、BMI270、MR20、BLE 和本地视频；固定双 detector 仅保留诊断兼容入口。
- Rev2 TM6605 改为左右独立有界持续状态机，0–4 震动等级一一映射；灯光 3/4 改为持续慢闪/快闪；音频改为每侧一个待播项、去重、四级抢占三级和 clear/stop 终止。未找到可确认的 TM6605 线性增益寄存器，不声称线性振幅。
- 增加固定 `/root/smartbag/venv`、模型安装门禁、设备节点有界等待 JSON、`smartbag-safe-off.service`、boot self-test、`rev2-board-validation.py` 和本地/板端 session 目录。
- BLE alert 增加 effective/haptic/light/audio/接收时间字段；小程序历史改为 100 条，记录 BLE/Cloud 来源、执行器输出和有原因的解除事件，过滤 heartbeat 与短时完全重复事件。
- 后续按用户授权仅做 USB-UART 非生产暂存和摄像头隔离验证：代码暂存到 `/root/smartbag-staging/a660901`，未执行生产安装、systemd enable、执行器通电或 power-only 验收。
- 双 UVC 请求 `1680x1050 MJPEG @10` 实际输出 1920x1080；10/10 次交替、左右各 20 帧通过，无流错误，最大 capture-only 盲区 545.945 ms。重启后数字 video 节点发生互换，进一步确认必须使用稳定物理路径映射。
- 两张快照完成板上 `yolov8n.om` NPU 推理并生成输出，纯模型执行约 25.44 ms；现场无项目目标类别。临时 ACL harness 的 `EnvDeinit()` 仍异常，正式 OM 后端和实时视觉链继续标记 BLOCKED。
- 新增 `serial_binary_transfer.py`，在仅有已登录 USB-UART console 时支持双向单文件传输、临时文件替换和三方 SHA-256 校验，并补充单元测试和使用说明。
- 本地最终验证运行 280 项 Python 测试（279 通过、1 项 Linux-only `fcntl` 跳过），并通过 6 个小程序测试文件、24 个 JS 语法、38 个 shell 语法、22 个跟踪 JSON、compileall、安全关断 dry-run 和仓库策略检查。
- 固定审计 `sanda-tt/ss928@970351c84a12f3219e7910ee488ac5ff579d6f98` 相对上次 `d7e10fd06dc553f94d2db3a3d19987ec8648f7dc` 的 19 个提交；没有合并上游历史或复制许可不明厂商资料。
- 新增 `rev2_tm6605_mr20` 和 `legacy_pwm_haptics` profile、配置迁移/回滚、唯一引脚表与 profile-aware pinmux；Rev2 的 Pin7/Pin32 只用于左右灯光。
- 新增统一 TCA9548A 原子事务与跨进程锁，BMI270 每笔访问重选 CH0，左右 TM6605 分别重选 CH1/CH2；新增 TM6605 和 PWM 灯光 backend、调度、状态和错误计数。
- 新增 MR20 14 字节帧、0x60A/0x60B、来源 IP/端口、scan 聚合、多帧确认、replay 和 `eth1` `/32` host route 工具。
- Controller 改为按 `(source, side)` 融合 vision/radar/manual；来源 timeout/clear 相互隔离，heartbeat 不入历史。后续 autonomous 更新将 Rev2 Level 1/2 恢复为触觉一级/二级，但灯光和音频仍关闭。
- 新增可选 Cloud uploader、HMAC/nonce/有界离线队列、CloudBase 用户绑定查询与小程序 BLE/Cloud 统一数据源。真实 CloudBase 未部署。
- 新增硬件 preflight、I2C/TM6605/灯光/MR20 工具、session 记录、可选 cloud systemd unit 和 CI 策略检查。实物输出和 MR20 目标帧仍按 BLOCKED 记录。

## 2026-07-19

- 完成交替双摄剩余软件链：新增真正进入视觉算法的端到端观测间隔、左右跨侧延迟、完整阶段时间戳和以 E2E max 为优先的验收口径；保留 capture-only 指标用于定位 USB 切换。
- 新增 `--inference-frames-per-slice`（默认 1）和无队列最新帧选择；新增跨独立 slice 的风险确认、单帧跳变/fast path 真实计数和 `effective_side` tracker 时间尺度。
- 交替 detector 内置左右 raw/overlay gateway、状态 API 与浏览器双画面；小程序改为 completion-driven refresh、每侧单 in-flight、页面隐藏停止、指数退避和单侧聚焦降频。
- 新增 side-specific 相机重连状态机及恢复事件日志、左右安装外参/背包坐标、标定检查器、依赖审计/安装脚本、轻量 preflight、session 清理 timer 和 GitHub Actions。
- 板端依赖审计确认 Python 3.10.12 当前缺少 cv2/numpy/torch/torchvision/Ultralytics/lap；确认 ACL 库和 sensor 专用 `.om` sample 存在，但通用 USB 内存帧 API/配套 SDK 信息不足，`Ss928OmBackend` 继续标记 BLOCKED。
- 真实 SS928 30 分钟纯采集完成：1800.247 秒、3620/3620 切换、左右各 7240 帧，无 ENOSPC/STREAMON/OFF/首帧错误；capture-only 最大盲区 580.264 ms。左右 sysfs 逻辑断连均约 3 秒恢复，另一侧继续工作。
- 长测发现诊断历史容器会增长，现已改为有界 deque，并以累计量保留精确总数、均值和峰值；同时修正无模型测试入口遗漏每侧 reconnect counter、session reconnect 总数未按侧汇总的问题。
- 无模型采集入口现在明确记录 `selected_for_inference=false`，避免把纯采集帧误写为已选推理帧；旧 A6 session 的该字段已在摘要中标注不可作为推理证据。
- session summary 新增 capture-only p50/p95/p99 和左右 E2E p50/p95/p99；A6 原始 switch 记录计算出的 capture-only 分位数为 489.126/519.877/569.307 ms。
- 板端 APT 因 `eth0 linkdown` 和 DNS 失败无法安装视觉依赖；raw 网关已板端本机验证，带检测框 overlay、完整 E2E、PWM、BLE 和微信真机继续明确标记 BLOCKED。
- 新增默认关闭的 `alternating_single_model` 实验模式：一个主进程只加载一次 YOLO，左右 UVC 使用原生 V4L2 mmap 和显式 `VIDIOC_STREAMON/OFF` 交替采集；C 入口每个时间片取帧后立即 STREAMOFF，再执行推理。
- 左右分别持有 BoT-SORT、StableTrackId、TrackState、RiskModel、RiskWarningStabilizer、SelfObjectFilter、标定和 risk CSV；共享模型使用 `predict()` 后接独立 tracker，不交替复用 `model.track(persist=True)`。
- 告警协议区分 `state_change` 和 `heartbeat`：无观测不等于 SAFE，切换侧不误清旧状态，陈旧观测/进程退出最终清振；heartbeat 只刷新 PWM timeout，不写入 BLE/手机历史。风险优先调度只读取多帧稳定后的 haptic 等级。
- 新增 A/B 诊断、缓存双画面 gateway、完整 session/CSV/summary 记录、实验矩阵、控制/报告脚本和互斥 systemd service；原始 session 继续放在被忽略的 `08_media/alternating_camera_runs/`。
- SS928 实板 A1-A4 共 989 次切换，成功率 100%，无 ENOSPC；p95 切换 273.726-278.018 ms，最大盲区 539.016 ms，左右有效约 4.08-4.13 FPS。B 阶段左右 snapshot/status/debug page 可用，退出后无相机占用。
- 额外 `1680x1050@10` 请求被驱动协商为 `1920x1080@30`；30 秒 61/61 次切换成功、无 ENOSPC，p95 278.613 ms、最大盲区 509.999 ms。文档明确不把请求值当成实际模式。
- 驱动把请求的 5/10 FPS 均协商为 MJPEG 30 FPS；纯采集 30 分钟已通过，但板端仍缺 OpenCV、PyTorch、Ultralytics 和 lap，完整 C/D 未上板，因此正式默认保持 `fixed_dual_process` 和 `alternating_camera.enabled=false`。
- 本地分模块共 229 项 Python 测试与 4 个小程序 JavaScript 测试文件通过，真实 Ultralytics 单模型/双 BoT-SORT 冒烟通过；板端转移运行时代码 compileall、全部部署 shell 语法和 16 个跟踪 JSON 解析通过。板端风险 overlay 测试因明确缺少 cv2 未执行。

## 2026-07-16

- 正式板端部署从单摄默认改为左右两个固定 USB detector：每个进程只打开一次对应相机，左事件只驱动左 PWM，右事件只驱动右 PWM；旧 `--single-camera/--side auto` 仅保留兼容测试。
- 新增 `board_dual_balanced`、容量 1 latest-frame capture、`--camera-fps`、`--inference-fps-limit`、`--process-every-n`、有限断流重连和左右 `[left]/[right]` profile；保留原 Future Conflict Gate、多帧稳定和 haptic 输出。
- 新增 detector-local snapshot/MJPEG 服务和 `dual_camera_gateway.py`，提供双路状态、raw/overlay snapshot、MJPEG 与浏览器调试页；手机慢客户端不阻塞检测，摄像头不会被第二个推流进程重复打开。
- Controller 新增双摄配置生成、跨侧事件拒绝、单侧退出清振/有限重启、自动 BLE alert、资源/重启状态文件；`SYS STATUS` 不再伪造电量。
- 微信小程序新增“双摄实时画面”、板端地址/path/token/storage、raw/overlay、暂停/重连、左右风险与自动告警历史；视频明确只走 Wi-Fi/LAN，不走 BLE。
- 新增双标定模板、双摄/依赖/stream 测试脚本、`smartbag-video.service`、双摄默认 target、完整部署说明和本地 SS928 归档审计。MIPI/VO 不进入默认启动链。
- 真实 SS928 只读验证确认双 UVC 枚举和单路出帧，但当前两台相机共用 USB 2.0 hub，双路 640x480/320x240 均出现一侧 `ENOSPC`；当前 952 MiB 内存且缺少板端视觉依赖，未宣称双 detector 已运行。
- 本地通过 203 项 Python 测试、4 个小程序测试文件、compileall、16 个 JSON、14 个 JavaScript、15 个 shell 语法和 `git diff --check`。不同 USB 根控制器复测、视觉依赖、温度、微信真机和 `.om` 后端仍待验证。

## 2026-07-15

- 从只读来源 `sanda-tt/ss928@d7e10fd06dc553f94d2db3a3d19987ec8648f7dc` 选择性整合 IMX347、BMI270、跌倒检测、DX-GP21、震动/音频控制、小程序和板端调试工具，没有合并来源 Git 历史。
- 视觉程序新增 `board_cpu`、`DetectorBackend`、`--camera-device`、单/双摄方向参数和稳定 haptic `vision_alert` JSONL；stdout 只输出事件，普通日志转 stderr。
- Controller 增加配置化四路 PWM、事件过期/格式校验、detector 退出清振、单摄默认模式、统一 BLE 命令路由和可选非阻塞音频。
- GNSS/BMI 默认关闭独立 BLE，统一广播名为 `SS928-SmartBag`；BMI 样本直接进入独立 fall detector 事件链。
- 建立 SS928 40Pin 唯一事实源、板端需求/设计/来源清单、统一部署包和跨模块集成测试。
- 删除活动 `radar_visualizer`、旧雷达实现计划、跟踪的 YOLO/ONNX 权重和本地生成物；当前风险判断保持纯视觉。
- 来源 SDK、二进制、BMI270 blob、原始校准 CSV 和许可不明音频未迁移；部署提示音为本项目生成的短测试音且默认关闭。

本文件记录已经上传到 GitHub 的项目更新。以后每次有实质功能、参数、文档或调试流程变化，都要在提交前增加对应记录。

## 2026-07-07

- 新增底部自身前景过滤 `SelfObjectFilter`，用于忽略画面下沿被截断且固定在底部的车把、背包边缘、身体边缘、支架等误检，默认参数为 `--self-mask-bottom-ratio 0.92`，并提供 `--disable-self-object-filter` 做对比调试。
- 风险输出新增 `visual_risk_level` 和 `haptic_risk_level`：画面可以显示远处候选 ATTENTION，未来震动模块使用更严格的 haptic 风险；远处 REMOTE 车流没有路径冲突时默认不震动。
- 强化 remote traffic 和 future conflict gate：`path_conflict=False`、`moving_away=True` 或 CPA 最近点已经过去的目标不能升级为高等级震动预警；large vehicle 只有未来进入个人空间或前方走廊时才允许实际升级。
- 新增边缘截断保护 `edge_truncated_cap`：左右边缘截断、距离/速度置信度低、track 太短或位置抖动大的车辆，单帧 CPA/TTC 跳变最多作为 ATTENTION 候选，不允许直接 DANGER/EMERGENCY。
- risk CSV 新增 `ignored_reason`、`self_object_score`、`bbox_bottom_ratio`、`bbox_truncated_edges`、`visual_risk_level`、`haptic_risk_level`，便于区分 self object、边缘截断、远处交通 cap、future conflict 判断和 stabilizer 升级问题。
- 更新根目录 README 和视觉模块 README，新增 “Self Object / Bottom Foreground Filter” 和 “Visual Risk vs Haptic Warning” 说明、推荐调试命令以及误报验证方法。
- 继续优化 `06_software/vision_obstacle_tracker` 纯视觉避障风险判定，不修改雷达相关目录。
- 新增 Future Conflict Gate：先判断目标未来有限时间内是否进入个人安全圆或前方有限行走走廊，`path_conflict=False` 时 TTC/DRAC/closing speed 不能推动到 CAUTION 以上。
- 新增并写入 risk CSV 字段：`moving_away`、`approaching`、`path_conflict`、`will_enter_personal_space`、`will_enter_warning_corridor`、`personal_entry_time_s`、`corridor_entry_time_s`、`min_future_distance_m`、`conflict_reason`、`distance_trend_mps`、`approach_consistency`、`path_conflict_consistency`。
- 强化远离和跳变保护：`moving_away_no_future_conflict` 强制 SAFE，`no_corridor_entry` 限制无路径冲突目标，`unstable_single_frame_cpa` 限制单帧 CPA 异常。
- 更新 `RiskWarningStabilizer`：CAUTION/DANGER/EMERGENCY 在路径冲突一致性和接近趋势不足时会增加确认帧数，震动输出继续使用 `display_risk_level`。
- 更新根目录和视觉模块 README，新增“Future Conflict Gate / 未来冲突闸门”说明、risk CSV 排查字段和误报判定方法。
- 新增 `SeverityProfile` 类别严重性配置，将目标分为 `large_vehicle`、`small_rider`、`unknown_or_other`，分别配置 ATTENTION/CAUTION/DANGER/EMERGENCY 时间窗、警戒半径和个人安全半径。
- 将风险输出明确分为候选层 `raw_risk_level` 和实际显示/震动层 `display_risk_level`：大车可以更早形成候选预警，但显示和震动仍经过多帧确认、质量检查和降级迟滞。
- 新增 `warning_action` 震动动作映射：`none`、`short_weak_pulse`、`medium_interval_pulse`、`strong_fast_pulse`、`continuous_high_frequency`。
- 新增并写入 risk CSV 字段：`severity_class`、`warning_action`、`warning_time_horizon_s`、`warning_radius_m`、`risk_action_reason`，继续保留 CPA、corridor、risk cap 和 stabilizer 调试字段。
- 调整 `RiskWarningStabilizer`：CAUTION 默认需要 2 帧确认，DANGER 默认需要 3 帧确认，EMERGENCY fast path 只允许极近距离或高质量极短 TTC/CPA，避免单帧距离/速度跳变直接强震。
- 更新 overlay debug 内容，默认 normal 仍保持短标签，debug 才显示 severity、action reason、cap reason 和完整风险项。
- 补充单元测试覆盖远处横向汽车、大车远处路径冲突、汽车/卡车/公交提前预警、低速侧边自行车、高速摩托、当前进入个人空间、短 track/速度抖动、单帧跳变和 risk CSV 新字段。
- 更新根目录 `README.md` 和 `06_software/vision_obstacle_tracker/README.md`，新增预警等级语义、震动提醒映射、类别提前量、raw/display 两层输出和推荐调试字段说明。
- 继续遵守不上传 `08_media/`、`10_archive/`、测试视频、生成 risk log、本地构建产物和大体积第三方依赖目录的规则。
## 2026-07-02

- 优化纯视觉避障风险判定，新增 CPA（未来最近接近点）指标：`cpa_time_s`、`cpa_distance_m`、`cpa_valid`。
- 新增佩戴者前方走廊分区：`PATH`、`SIDE`、`REMOTE`、`SIDE_STATIC`、`UNK`，并写入 risk CSV。
- 新增风险上限机制 `risk_cap_reason`，用于限制远处横向交通流、路边静止目标、低速非路径目标、短 track 和速度不稳定目标的误报。
- 改进 `TrackState` 速度估计，使用鲁棒短历史速度，新增 `velocity_stability` 和 `position_jitter_m`，降低 bbox/单目测距跳变造成的虚假 CUTIN。
- 新增 `--overlay-verbosity minimal|normal|debug`，默认 `normal` 缩短画面标签，`debug` 才显示完整风险调试信息。
- 更新 `06_software/vision_obstacle_tracker/README.md`，新增真实场景风险语义、CPA/走廊/risk cap 调试说明和推荐命令。
- 更新根目录 `README.md`，让 GitHub 项目主页同步说明本轮风险误报修复、risk log 字段和 overlay 调试方法。
- 补充测试覆盖路边静止摩托、慢速侧边自行车、横切进入个人空间的自行车、远处横向车流、正前方快速接近汽车、短 track/速度抖动目标、CSV 字段和 overlay 参数。
- 保留既有 ROI、YOLO 类别前置过滤、OpenVINO 优先加载、camera calibration、pitch 调节、ego-motion、risk CSV、display-every-n、cpu_demo profile 等功能。

## 2026-07-02 之前

- 将根目录 GitHub 项目主页 `README.md` 改为中文说明，并补充安装、视频检测、摄像头实时检测、OpenVINO、风险日志、保存视频、性能剖析和调试方法。
- 新增 `CHANGELOG.md`，用于记录每次上传到 GitHub 的更新内容。
- 明确以后每次功能更新都要同步更新相关 README 和本更新记录。
- 明确 `08_media/`、`10_archive/`、视频文件、生成的风险日志、本地构建产物和大体积第三方依赖目录不上传 GitHub。
- 近期视觉避障性能优化包括：YOLO 类别前置过滤、`--roi-top-ratio` ROI 顶部裁剪、`--prefer-openvino` 优先加载 OpenVINO、`--profile` 性能剖析、`--display-every-n` 窗口刷新降频。
- 近期视觉风险调试优化包括：风险 CSV 日志、运行预设、相机自运动质量记录、显示层风险稳定器、距离质量标志、风险分项诊断。
