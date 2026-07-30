# 更新记录

## 2026-07-30

- 准备 `smartbag-v1.0.0-rc2`：正式 `vehicle-detector.om`、AArch64 runner/inspector、AGPL-3.0-only License、模型/音频/第三方声明和一键安装入口进入普通 Git clone 与离线包；静态契约通过，板端 ACL 检测仍明确为 `PENDING`。
- `radar_only` 与 full 模式统一使用 `RadarVisionFusionRuntime`、持久雷达轨迹、共享 RiskModel 和每目标 0.5 秒中位数；旧 MR20 阈值算法只保留为显式 `legacy_mr20_threshold_test`。
- HTTP API 默认 loopback，安装时生成管理/只读 Token；所有读取接口鉴权，PATCH/reset 仅管理 Token，使用常量时间比较，preflight 拒绝不安全公网监听。
- 修复雷达/相机高度实际投影、固定 fx 时 FOV 只读推导和参数 requested/effective/source；危险图片增加 frame 缓存和跨帧错配保护。
- 风险窗口新增样本数、观测时长、完整扫描率和雷达质量门限，以及严格双样本极近 fast path；单样本不再产生正式 L3/L4。
- 摄像头发现按物理身份去重并交互确认左右，MR20 增加网络/UDP/0x60A/0x60B/完整扫描 live check、worker 健康与指数退避恢复；事件历史增加数量、图片、容量和天数保留策略。
- 首装增加 SS928/架构/内存/磁盘、OM/runner、相机身份、雷达网络、融合标定与 safe-off 检查；标定记录 RMSE、最大误差、相机身份和雷达名称，硬件变化会阻止 full。
- 新增 GitHub Actions，覆盖 395 项 Python、12 个 Node 测试文件、5 项 C/C++ native、compileall、44 个 JSON、33 个 Shell、secret、manifest、干净 clone、mock 安装和 release 包。
- 审计三个远程分支、PR #6/#7、tag/Release、stash/LFS/fsck 和祖先关系；旧分支相对最终候选均无独有提交，归档 tag 与 main-only 收敛按 `00_admin/final-branch-consolidation-plan.*` 执行。

### 同日早期审计记录（已被上述 RC2 结论替代）

- 取消 `08_media/` 的整目录忽略，改为精确排除个人测试视频、检测输出、板端日志、第三方 SDK/runtime、工具链和构建缓存；允许经确认的模型与硬件参考资料进入 Git。
- 提交两处内容相同的 YOLO11n SS928 OM 候选、转换 manifest 和 SHA256 校验文件；候选 OM 仍为实板验证和正式许可待确认状态，不进入 RC Release，也不会绕过部署 preflight。
- 对当前仓库、Git 历史、ignored 目录、`08_media`、`10_archive`、同级目录、旧板端记录、模型、runner、SDK 和工具链执行部署资产审计；生成匿名路径的 CSV/JSON/Markdown 清单，共登记 1,495 个候选文件、21 个模型和 524 个 ELF，不复制厂商 SDK、镜像、日志或私密配置。
- SS928 detection runner 改为读取 ACL 模型 descriptor 后自动选择 NV12 UINT8、RGB_PLANAR UINT8 或 RGB_PLANAR FP32 预处理，严格校验 `[1,84,8400]` FP32 输出；Python 后端统一发送 BGR24。源代码契约测试通过，但 OM 实板 descriptor/检测对齐仍为 `PENDING`。
- 使用本地合法工具链输入构建并打包 AArch64 `ss928_detection_runner` 和 `om_inspect`，记录架构、动态依赖、构建来源和 SHA256；ACL runtime 继续由匹配的板端镜像提供，不复制厂商 `libascendcl.so`。
- 本地 YOLO11n PT/ONNX 在三张私有视频帧上完成同图框/类别比较；候选 OM 缺少 SS928 实测且正式许可仍待确认，现按项目所有者要求进入 Git，但不进入 RC Release，完整视觉安装保持阻塞。
- 新增根目录一键安装入口、radar-only 安全降级、mock root 重复安装、配置/事件保留升级、卸载保留用户数据、失败 safe-off、runner/model SHA/架构/契约校验和板端依赖检查。
- 新增左右 UVC 物理端口发现/顺序抓帧/udev 稳定链接流程，新增双 MR20 硬件 profile；历史端口仅作候选，安装时必须重新确认。
- 融合标定模板明确标为 `UNMEASURED_TEMPLATE`，新增采样字段、水平 yaw/fx/cx 拟合、RMSE 校验和板端脚本；没有把占位外参冒充当前安装位姿。
- 新增小程序部署说明、空 AppID/CloudBase 模板、离线 radar-only 发布包构建、依赖 manifest、发布就绪 JSON、凭据扫描器和克隆安装缺口清单。
- 本机通过 385 项 Python、12 个 Node 测试文件、4 个 NPU native C++、C 核心与 C++ backend 测试，以及 compileall、38 个 JavaScript、42 个 JSON、30 个 Shell 和 `git diff --check`。真实板端安装、模型识别、标定、reboot 和独立供电仍未验证。

## 2026-07-28

- 全量审计 Git、ignored/LFS、历史分支、父目录备份和旧实测产物，生成 `00_admin/local-model-inventory.md/.json`。选中 YOLO11n OM 候选并统一部署名 `vehicle-detector.om`；因 RGB_PLANAR AIPP 与当前 NV12 runner 不兼容，manifest/preflight 明确保持 BLOCKED。
- 交替快照改为 Linux 原生 V4L2 持久 fd/mmap：两路预打开但最多一路 STREAMON，支持首次/切换预热、捕获/关流超时、单侧退避，以及 0.20 秒目标调度的 overrun、p50/p95/max 和每侧 FPS 统计。
- 正式融合移除雷达/视觉混合 queue，改为锁保护的最新完整扫描、当前雷达轨迹、最新快照/检测/车型映射和风险窗口；视觉回调不阻塞雷达风险采样。
- `VisualClassBindingManager` 退出正式路径。每张图片按水平区间重合、时间、中心距离和弱尺寸代价做 Hungarian 一一匹配，并原子替换本侧全部车型；未匹配、歧义或超时均为 unknown。
- MR20 增加完整/不完整扫描组包与统计；零目标是合法完整扫描，不完整扫描保留已收目标但不会增加其他轨迹 miss 或触发删除。
- 新正式模式以每轨迹固定 0.5 秒风险 score 中位数替换旧帧数 stabilizer，支持运行时 `warning_sensitivity`；旧 stabilizer 继续供 `legacy_dual_vision`。
- 新增运行参数 GET/PATCH/reset API、小程序“系统参数”页、三级/四级事件 JSONL/同侧 JPEG、历史/详情/图片 API、小程序本地去重/图片保存/重试和 CloudBase 异步降级。
- 扩展融合状态和调试快照，显示扫描完整率、窗口样本/中位数、车型映射、切换/YOLO/关联耗时，以及投影容差区间、bbox 扩展、重合段和 ambiguous。
- 从 `agent/full-sanda-integration@c3ef9c012543cdc02c708449572e8645b98dcf48` 创建 `agent/radar-primary-vision-class-fusion`，实现 MR20 主导、视觉只提供车型的目标级融合架构。
- MR20 worker 新增完整 `RadarScan`、有界队列和目标元数据；保留旧最高告警接口作为兼容，不再用于新正式模式。
- 新增持久雷达轨迹、安装坐标变换、ID generation、时间同步投影、Hungarian 一一关联、车型确认/缓存/切换/解绑状态机和 JSONL 回放。
- RiskModel 改为传感器无关 `KinematicRiskTarget` 输入，视觉与雷达调用相同 CPA、Future Conflict、TTC、DRAC、车型权重和 visual/haptic 公式；新增 base/weighted score 调试字段。
- 新增单模型交替快照分类器；任意时刻最多一路 UVC STREAMON，不运行 BoT-SORT、视觉测距测速或视觉风险。OM runner 增加模型只初始化一次的 stdin 服务模式和 BGR-to-NV12 桥接。
- Controller 新增 `radar_primary_visual_classification`，该模式不会并行启动旧双视觉 detector 或旧简单雷达 evaluator；无视觉时以 unknown=1.0 继续雷达风险判断。
- 扩展融合告警、BLE 可选字段、调试 API、左右标定模板、部署配置和 preflight；旧双 detector 视频网关退出默认 systemd target，但保留手动回归。
- 修复跨侧绑定清理、严格水平关联门限和 `R * P + T` 外参顺序；增加 runner 超时重启、相机异常隔离、heartbeat 语义、扩展 BLE/小程序字段，以及按运行模式/backend 检查且 OM 模式不强制 PyTorch 的 preflight。
- 本地通过 367 项 Python、12 个 Node 测试文件、4 个 NPU native C++ tests、1 个 C 兼容核心测试、37 个 JavaScript、33 个 JSON、21 个 Shell 和 compileall。5.25 秒纯模拟调度的相邻启动间隔 p50/p95 为 200.56/201.24 ms、左右约 2.38/2.49 FPS、最大并发流为 1；这不是实板性能。真实双 MR20、合法车辆 OM、外参、30 分钟、自启动和脱机运行仍为 `BLOCKED`。

## 2026-07-26

- 完成 `sanda-tt/ss928@59071297e5d8f339332a7234406429f94ffe2570` 的 24,421 个 Git blob 全量审计；manifest 记录每个来源文件的 SHA-256、用途、目标落点、动作和测试状态，并由独立脚本重算校验。
- 在现有固定左右双 USB detector、Future Conflict Gate、多帧稳定和 visual/haptic 风险链基础上，整合 MR20、TCA9548A/TM6605、左右 PWM 灯、BMI270 驼背/跌倒、MT5710、CloudBase、Tsensor、WS73、小程序、CAD 和 SS928 OM 实验后端；未恢复交替双摄正式方案。
- Controller 改为按 `(source, side)` 融合，单一视觉/雷达来源清零不会误清其他来源；新增 TM6605、灯、异步音频、MR20 worker、跨进程 I2C mux 锁和驼背 `posture:hunch` 双侧提醒。
- 正式硬件默认调整为 TCA channel 0 BMI270、channel 1/2 左右 TM6605，Pin7/Pin32 灯；Pin35/Pin37 仅作 legacy PWM 兼容。增加 WS73 可选 module loader 和 MR20 networkd 示例，不自动写入板端网络。
- MT5710 service 只拥有 NCM 连通性，不再重复拉起 BMI/GNSS；Cloud/SMS/call 故障不阻塞本地告警，GNSS 无有效 fix 时省略位置，温度失败返回明确状态。
- 微信小程序保留原有双摄/monitor/tracks/BMI 页面，新增 CloudBase 告警、云端姿态、统一 BLE remote；移除 quickstart/example/placeholder 脚手架入口，Cloud 环境和上传 token 外置。
- 增加统一部署的 config migration、hardware profile、safe-off、connectivity/temperature/WS73 units 和配置保留升级流程。
- SS928 NPU 只接入经 native tests 验证的模型合约、NV12 预处理、YOLO 解码和离线 detections JSONL。来源固定输入 ACL 性能证据被保留，但真实 OM 检测与双 USB 实时 tracker/risk bridge 仍明确标为硬件阻塞。
- 新增完整整合架构、许可边界、来源索引和中文部署文档；来源 LFS 缺失对象、含密码 handoff、SDK/模型/日志/构建物未迁移。
- 收尾验证通过 290 项 Python 测试、11 个小程序/CloudBase Node 测试文件、4 个 NPU native C++ tests、32 个 JavaScript、27 个 JSON、21 个 Shell 和逐文件 manifest 校验；当前板端 SSH 不可达，部署/自启/硬件结果保持未验证。

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
