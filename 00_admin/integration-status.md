# SS928 全量整合与雷达视觉融合状态

## 2026-07-28 当前分支

- 开发基线：`agent/full-sanda-integration@c3ef9c012543cdc02c708449572e8645b98dcf48`。
- 当前分支：`agent/radar-primary-vision-class-fusion`。
- 正式候选数据流改为：双 MR20 完整扫描 -> 持久雷达轨迹 -> 单模型左右交替快照车型分类 -> 水平重叠硬门限与 Hungarian 一一关联 -> 每张图片原子替换本侧车型映射 -> 原视觉 RiskModel -> 每轨迹固定 0.5 秒风险中位数窗口 -> 每侧最高 haptic -> Controller。
- 新模式关闭旧 MR20 简单风险 evaluator，不启动两个完整视觉 detector，也不运行 BoT-SORT、视觉测距测速、光流或视觉 CPA。`legacy_dual_vision` 仅保留回归。
- OM 后端已有持久 runner、BGR24 传输、5 秒默认响应超时、进程重启和一次重试；runner 根据 ACL descriptor 自动选择 NV12 UINT8、RGB_PLANAR UINT8 或 RGB_PLANAR FP32 输入。源代码契约测试通过，但候选 OM 的真实板端 descriptor、车辆检测对齐和再分发许可仍未通过，正式模型部署状态保持 `BLOCKED`。
- 默认 profile 使用安装时生成的 `/dev/smartbag-camera-left/right` 稳定链接；历史 by-path 只作发现提示。左右融合模板明确标记为 `UNMEASURED_TEMPLATE`，完整模式 preflight 要求实测标定。

## 本分支本机验证

- 385 项 Python 测试通过：视觉 148、板端模块与录像工具 160、跨模块集成 77。
- 12 个小程序/CloudBase Node 测试文件通过；38 个 JavaScript 文件通过 `node --check`。
- 4 个 SS928 NPU native C++ tests、1 个 C 兼容核心测试和 1 个 C++ backend 测试通过。
- `compileall`、42 个 JSON、30 个 Shell、凭据扫描和 `git diff --check` 通过。
- 模拟测试覆盖完整/不完整 MR20 组包、多目标 generation、安装变换、原生 V4L2 持久资源与交替单 STREAMON、水平重叠硬门限、Hungarian 一一匹配、歧义 unknown、每图原子车型映射、共享 RiskModel、0.5 秒中位数窗口、运行参数原子更新、三级/四级事件持久化、JSONL 回放和故障降级。
- 5.25 秒纯模拟相机调度中，相邻快照启动间隔 p50 为 200.56 ms、p95 为 201.24 ms，左/右模拟快照频率约 2.38/2.49 FPS，最多一路 STREAMON；首次启动有一次 437.40 ms 峰值并记录 1 次 overrun。该结果不包含真实 USB、解码、OM/NPU 或板端资源开销。

## 当前硬件阻塞

2026-07-28 收尾检查时，Windows 的物理以太网接口均为 `Disconnected`，板端私网地址无 ICMP/SSH 响应。因此没有执行本分支上传、systemd 启动或重启验收，以下结果保持 `BLOCKED`：

- 左右 MR20 实际配置、扫描频率、多目标数量、丢帧率和 30 分钟稳定性。
- 当前左右 UVC by-path、单 STREAMON 切换时延、每侧分类频率和失败恢复。
- 合法车辆 OM 的类别/框正确性、NPU 时延、CPU、RSS、温度和长期运行。
- 左右雷达-相机内外参、投影误差、单车/多车关联成功率和错误绑定率。
- 真实振动/灯/音频/BLE、systemd restart、reboot 自启和断网脱机运行。

下列内容是 2026-07-26 基线审计记录，保留用于来源追溯，不代表当前分支已完成实板验收。

## 仓库与审计

- 目标基线：`06c6cfd1dc11a0f92c54ce8aad5252d554ececa5`。
- 来源基线：`sanda-tt/ss928@59071297e5d8f339332a7234406429f94ffe2570`，只读使用。
- 来源 24,421 个 Git blob 均进入 `sanda-full-file-manifest.csv`；路径、大小和 SHA-256 由校验器重新核对。
- 5 个缺失 Git LFS 对象和 1 个含设备凭据 handoff 标为 `BLOCKED`，不伪造、不提交。

## 2026-07-26 已完成整合

- 固定左右双 USB detector、独立 tracker/risk/stabilizer/risk CSV、latest-frame HTTP、双路 gateway 和统一 Controller 保持不变。
- Controller 按 `(source, side)` 融合视觉和可选 MR20；单来源清零、超时或退出不会清除另一来源或另一侧。
- TCA9548A 通道分配：BMI270=0、左 TM6605=1、右 TM6605=2；BMI/TM 使用同一跨进程 I2C 锁。
- 正式输出：左右 TM6605/LRA、Pin7/Pin32 灯、可选 MAX98357；Pin35/Pin37 只保留 legacy PWM 后端。
- BMI270 单进程姿态、累计驼背提醒、跌倒融合、CloudBase、可选短信/电话；驼背输出使用独立 `posture:hunch` 来源，不覆盖交通风险。
- DX-GP21、MT5710 NCM、Tsensor、WS73、CloudBase、小程序和硬件 profile 接入统一部署；可选模块故障不阻塞本地视觉和安全清零。
- 云函数必需 `lib/*.js` 已纳入 Git；Cloud env、token、手机号和板端凭据不写死在公开配置。

## 2026-07-26 SS928 NPU 状态

- 已完成：ACL I/O 合约、NV12 letterbox、YOLO decode/NMS、离线 raw runner、detections JSONL 协议和 4 项本机 native C++ tests。
- 来源历史证据：固定输入 100 帧 ACL 平均推理约 25.112 ms、后处理约 16.292 ms、总吞吐约 23.348 FPS。
- 未完成：工厂 OM 的真实目标正确性、USB 实时输入、双路 NPU 调度、detections 到现有 BoT-SORT/TrackState/RiskModel/overlay 的实时桥接。
- 因此当前正式实时后端仍是 Python Ultralytics；不得宣称完整 NPU 避障链已可用。

## 2026-07-26 测试状态

整合前基线共 203 项 Python 测试通过。整合后本机验证结果：

- 290 项 Python 测试通过：视觉 147、USB 录像 8、BMI270 22、Cloud 6、GNSS 6、IMU/fall 11、MR20 7、MT5710 23、Controller 17、温度 3、跨模块集成 40。
- 11 个小程序/CloudBase Node 测试文件通过；32 个 JavaScript 文件通过 `node --check`。
- 4 个 SS928 NPU 后端 C++ native tests 通过，并验证 Windows/Linux 双平台 `make clean` 路径。
- `compileall`、7 个关键模块 import、27 个 JSON、21 个 Shell、配置同步、manifest 全量校验、重复哈希、大文件、secret 和 `git diff --check` 检查通过。
- 仓库根目录直接运行 `python -m unittest discover -v` 因测试分散在各非包模块目录而发现 0 项；最终结果来自各模块与 `07_tests/integration` 的显式 discovery，不把 0 项 discovery 记作测试通过。
- 本机无 WSL/systemd 环境，无法运行 `systemd-analyze verify`；systemd 路径、默认 target、硬件所有权和可选服务故障隔离由 40 项集成测试中的部署断言验证。

## 既有实板证据

- 2026-07-16 记录：SS928V100、Ubuntu 22.04.1/aarch64、Linux 4.19.90、4 CPU、约 952 MiB RAM。
- 两台 `0bda:3035` UVC 当时分别枚举为 `/dev/video0`、`/dev/video2`，同序列号导致 by-id 冲突；共同位于 USB 2.0 hub 时双路出现 `ENOSPC`。
- 这些是历史基线，不等于本分支已在当前接线完成部署、自启或端到端检测。

## 2026-07-26 当时未完成的硬件验收

2026-07-26 本轮收尾时 Windows 物理以太网适配器状态为 `Disconnected`，已知板端地址均无 ICMP/SSH 响应，因此没有执行上传、服务启动或 reboot。以下项目保持未验证：

- 两路相机当前 by-path、不同根控制器、30 分钟持续采集、断流重连、detector FPS/CPU/RAM/温度。
- 两份相机内参/畸变/高度/pitch 和实景风险日志。
- TCA channel、TM6605/LRA、灯、MAX98357、BMI270、MR20、DX-GP21、MT5710、WS73、Tsensor 的实际端口和供电。
- Controller 清零、Cloud/5G 断网、systemd restart、reboot 自启和 safe-off。
- 微信小程序真机 BLE/局域网/CloudBase；正式 AppID、HTTPS 和合法域名。
- 真实可用 OM、双路 NPU 实时链与 Python 风险结果对齐。
