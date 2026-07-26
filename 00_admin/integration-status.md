# SS928 全量整合状态

## 仓库与审计

- 目标基线：`06c6cfd1dc11a0f92c54ce8aad5252d554ececa5`。
- 来源基线：`sanda-tt/ss928@59071297e5d8f339332a7234406429f94ffe2570`，只读使用。
- 来源 24,421 个 Git blob 均进入 `sanda-full-file-manifest.csv`；路径、大小和 SHA-256 由校验器重新核对。
- 5 个缺失 Git LFS 对象和 1 个含设备凭据 handoff 标为 `BLOCKED`，不伪造、不提交。

## 已完成整合

- 固定左右双 USB detector、独立 tracker/risk/stabilizer/risk CSV、latest-frame HTTP、双路 gateway 和统一 Controller 保持不变。
- Controller 按 `(source, side)` 融合视觉和可选 MR20；单来源清零、超时或退出不会清除另一来源或另一侧。
- TCA9548A 通道分配：BMI270=0、左 TM6605=1、右 TM6605=2；BMI/TM 使用同一跨进程 I2C 锁。
- 正式输出：左右 TM6605/LRA、Pin7/Pin32 灯、可选 MAX98357；Pin35/Pin37 只保留 legacy PWM 后端。
- BMI270 单进程姿态、累计驼背提醒、跌倒融合、CloudBase、可选短信/电话；驼背输出使用独立 `posture:hunch` 来源，不覆盖交通风险。
- DX-GP21、MT5710 NCM、Tsensor、WS73、CloudBase、小程序和硬件 profile 接入统一部署；可选模块故障不阻塞本地视觉和安全清零。
- 云函数必需 `lib/*.js` 已纳入 Git；Cloud env、token、手机号和板端凭据不写死在公开配置。

## SS928 NPU 状态

- 已完成：ACL I/O 合约、NV12 letterbox、YOLO decode/NMS、离线 raw runner、detections JSONL 协议和 4 项本机 native C++ tests。
- 来源历史证据：固定输入 100 帧 ACL 平均推理约 25.112 ms、后处理约 16.292 ms、总吞吐约 23.348 FPS。
- 未完成：工厂 OM 的真实目标正确性、USB 实时输入、双路 NPU 调度、detections 到现有 BoT-SORT/TrackState/RiskModel/overlay 的实时桥接。
- 因此当前正式实时后端仍是 Python Ultralytics；不得宣称完整 NPU 避障链已可用。

## 测试状态

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

## 仍需本轮真实硬件验收

2026-07-26 本轮收尾时 Windows 物理以太网适配器状态为 `Disconnected`，已知板端地址均无 ICMP/SSH 响应，因此没有执行上传、服务启动或 reboot。以下项目保持未验证：

- 两路相机当前 by-path、不同根控制器、30 分钟持续采集、断流重连、detector FPS/CPU/RAM/温度。
- 两份相机内参/畸变/高度/pitch 和实景风险日志。
- TCA channel、TM6605/LRA、灯、MAX98357、BMI270、MR20、DX-GP21、MT5710、WS73、Tsensor 的实际端口和供电。
- Controller 清零、Cloud/5G 断网、systemd restart、reboot 自启和 safe-off。
- 微信小程序真机 BLE/局域网/CloudBase；正式 AppID、HTTPS 和合法域名。
- 真实可用 OM、双路 NPU 实时链与 Python 风险结果对齐。
