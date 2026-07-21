# 基于 SS928 的智能背包

## 2026-07-22 视觉运行链更新

本项目的正式板端视觉链是：左右 UVC 按物理 `by-path` 交替采集，单个 SS928 `.om` 模型常驻 NPU，左右 tracker/轨迹历史独立，随后复用 PC 端同一套标定、背包坐标、测距测速、Future Conflict Gate、CPA、corridor、moving-away、风险模型和多帧/跨 slice 稳定器。震动控制只允许消费稳定后的 haptic level，不能读取 raw risk。

本轮新增了摄像头物理身份硬校验、每侧 rotation/flip、时间感知轻量 tracker、完整 session CSV、无 GUI 双摄标定工具、黑帧证据工具和 `vision_only_validation`。后者只开启相机、NPU、跟踪、风险、gateway 和日志，强制关闭 TM6605、灯光、音频、雷达、BLE、IMU、GNSS 与 pinmux 写入。

当前板端无法通过 SSH、历史 IP 或 USB 串口访问，真实黑帧恢复、双摄 `calibrated=true`、YOLO8/YOLO11 实景对比、1/2/3/5 米误差、30 分钟长测、两次重启和仅供电启动均未执行。当前结论是 `VISION_POWER_ONLY_NOT_READY`。详见 [完整视觉状态](02_research/complete-ss928-vision-status.md)、[PC/SS928 一致性审计](02_research/pc-to-ss928-vision-parity-audit.md) 和 [验收摘要](07_tests/results/complete-ss928-vision/latest-summary.md)。


视觉风险模型保持纯视觉：检测、跟踪、单目距离/速度、Future Conflict Gate、多帧稳定、visual/haptic 分层和自身前景过滤均由 `06_software/vision_obstacle_tracker` 完成。Rev2 板端另接 MR20 作为独立告警来源；它不改写视觉风险，而是在各自多帧确认后按 `(source, side)` 与视觉结果取同侧最大有效等级。

## 当前能力

- PC：USB 摄像头或视频输入，Ultralytics YOLO + BoT-SORT，ROI/OpenVINO CPU/profile，overlay、风险 CSV 和带框视频保存。
- SS928 Rev2：正式视觉后端使用一个常驻 `.om` 模型，经 SS928 ACL/NPU 处理双 UVC 原生 V4L2 交替采集；左右 tracker、距离/速度、风险稳定器和 overlay 独立。Controller 还监督 GNSS、BMI270、MR20、BLE 和本地视频 gateway。任一时刻只打开一侧 UVC，未激活侧显示缓存帧，不等同于同步双摄。
- 传感器：DX-GP21 GNSS/NMEA/轨迹；BMI270 IIO/I2C、姿态和短时运动趋势；独立跌倒/撞击事件。
- 移动端：统一 `SS928-SmartBag` BLE NUS 传告警/GNSS/IMU/系统状态；原生微信小程序显示左右画面、自动告警历史、轨迹和姿态。视频不走 BLE。
- Rev2 外设：TCA9548A CH0/1/2 分别接 BMI270、左/右 TM6605；Pin7/Pin32 驱动左右灯光；右后 MR20 使用独立 `eth1` `/32` host route。Level 1–4 均有对应侧触觉模式；Level 3/4 还持续驱动慢闪/快闪灯光和可选方向语音。
- CloudBase：可选 HTTPS telemetry 和小程序历史查询，默认关闭；板端 HMAC/nonce/离线队列与云端用户绑定不会取代本地 BLE 和本地告警。

## 快速入口

| 内容 | 文档/目录 |
|---|---|
| PC 视觉运行与调参 | [vision_obstacle_tracker](06_software/vision_obstacle_tracker/README.md) |
| 板端部署 | [board_deploy](09_deliverables/board_deploy/README.md) |
| 双 USB 板端资料审计 | [dual-usb-camera-board-analysis.md](02_research/dual-usb-camera-board-analysis.md) |
| 交替双摄分析与实测 | [alternating-dual-camera-analysis.md](02_research/alternating-dual-camera-analysis.md)、[alternating-camera-experiment-log.md](02_research/alternating-camera-experiment-log.md) |
| 板端架构 | [board-process-architecture.md](03_design/board-process-architecture.md) |
| 事件与 BLE 协议 | [event-protocol.md](03_design/event-protocol.md)、[ble-protocol.md](03_design/ble-protocol.md) |
| 40Pin 唯一接线表 | [40pin-usage.md](04_hardware/ss928/40pin-usage.md) |
| 来源审计与迁移决定 | [merge-manifest.md](00_admin/merge-manifest.md) |
| 本轮上游差异与来源 SHA | [sanda-upstream-refresh-analysis.md](02_research/sanda-upstream-refresh-analysis.md) |
| MR20 / TM6605 / CloudBase 状态 | [mr20-integration-status.md](02_research/mr20-integration-status.md)、[tm6605-tca9548a-validation.md](02_research/tm6605-tca9548a-validation.md)、[cloudbase-integration-status.md](02_research/cloudbase-integration-status.md) |
| 来源功能清单 | [ss928-source-inventory.md](02_research/ss928-source-inventory.md) |
| 清理与当前状态 | [cleanup-report.md](00_admin/cleanup-report.md)、[integration-status.md](00_admin/integration-status.md) |

## PC 视觉示例

```powershell
cd D:\mywork\code\embedded-contest-project\06_software\vision_obstacle_tracker
py -m pip install -r requirements.txt
py vision_obstacle_tracker.py --source camera --runtime-profile cpu_demo --profile
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --profile
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --save-output D:\path\overlay.mp4 --no-display
```

## SS928 快速部署

```sh
cd 09_deliverables/board_deploy
sudo sh install.sh /path/to/intelligent-bag-based-on-ss928 \
  /合法来源/yolov8n.om /可选/wheelhouse \
  /本机交叉编译/libsmartbag_ss928_acl.so
# 编辑 config、hardware、MR20 和左右 calibration，再检查
sudo sh smartbag-hardware-profile.sh show
sudo sh preflight.sh /etc/smartbag/config.json
sudo systemctl enable --now smartbag.target
sh logs.sh -f
```

安装器创建固定 `/root/smartbag/venv`、要求模型已随安装参数提供、安装 systemd unit 并 enable `smartbag.target`。新安装默认生成 Rev2 profile，旧设备可用 `smartbag-hardware-profile.sh set legacy_pwm_haptics` 回滚。GNSS 与 BMI270 默认 `--no-ble`，由 controller 独占 BLE。执行器只使用同侧融合后的稳定等级；来源清零、stale、进程退出、service stop 和关机都会执行安全清除。

默认采用 [board_deploy 交替双摄说明](09_deliverables/board_deploy/README.md#11-默认交替双摄模式)。每片默认只推理最新 1 帧，未激活侧是缓存帧；纯摄像头切换盲区与包含解码、推理、跟踪、风险、overlay 和 JPEG 的端到端观测间隔必须分开看。固定双 detector unit 仅保留为诊断兼容入口，不进入默认 target。

## 未完成与安全边界

- `Ss928OmBackend`、内存帧 ACL C ABI、YOLO 后处理和无 PyTorch tracker 已实现并通过 ARM64 交叉编译与单元测试；真实双摄连续 NPU、现场目标命中和 30 分钟 E2E 仍必须以板端日志验收，不能仅凭编译结果声明通过。当前证据见 [SS928 NPU 后端验收摘要](07_tests/results/ss928-npu-backend/latest-summary.md)。
- 2026-07-19 实板原生 V4L2 交替采集 A1-A4 共 989 次切换，成功率 100%，未出现 `ENOSPC`；B 阶段双缓存预览也可访问。最新 30 分钟、依赖、模型、PWM/BLE 和浏览器 overlay 验证状态见 [最新测试摘要](07_tests/results/alternating_camera/latest-summary.md)，任何 BLOCKED 项都不能按“已通过”解释。
- 模型、厂商 SDK、MPP、BMI270 config blob、设备密码/IP 不进入仓库。
- 单目测距和风险提示不是安全认证系统；真实使用前必须做相机标定、硬件在环、误报/漏报、时延、温度和断电恢复测试。
- MR20 0x60A/0x60B 解析和 replay 已自动测试；真实 0x60B 移动目标、TM6605 LRA、双灯、BLE 闭环和 30 分钟联合运行仍需新硬件实测，详见 [最新硬件刷新摘要](07_tests/results/hardware-refresh/latest-summary.md)。
- 2026-07-20 已完成双 UVC 交替采集及两张快照进入 SS928 NPU 的隔离测试。新的常驻模型实时后端不再逐帧调用临时文件 harness，但现场目标命中、长测和 power-only autostart 仍需重新验收；详见 [Rev2 autonomous 摘要](07_tests/results/rev2-autonomous/latest-summary.md)。
- 40Pin、PWM、LRA/灯光供电、I2S 和传感器电平必须按硬件文档核验，不能直接用 GPIO 给负载供电。CloudBase 源码未部署到真实环境，不能将 mock 测试解释为云端已上线。

`08_media/` 和 `10_archive/` 仅本地使用，不上传 GitHub。
