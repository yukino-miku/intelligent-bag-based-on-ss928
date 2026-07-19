# 单模型、双 USB 摄像头交替采集分析

## 结论

当前两台 UVC 摄像头位于同一个 USB 2.0 控制器和 Hub 下，同时 `STREAMON` 会触发 `ENOSPC`。原生 V4L2 交替 `STREAMON/OFF` 在 SS928 板端连续四组 2 分钟实验中均实现 100% 切换成功，未出现 `ENOSPC`。该方案存在约 0.51 秒的单侧最大盲区，只适合作为资源受限比赛原型，不等同于同步双摄，也不适合作为最终高安全等级产品方案。

## 审计过的资料

- 当前视觉程序、风险模型、controller、部署脚本和固定双 detector 服务。
- `02_research/dual-usb-camera-board-analysis.md` 中的既有 USB 诊断。
- `10_archive` 中 SS928 MPP Sample 的 `src/host_uvc/host_uvc.c`。该示例使用标准 V4L2 `S_FMT`、`S_PARM`、`REQBUFS`、`mmap`、`QBUF`、`STREAMON`、`DQBUF` 和 `STREAMOFF`，没有发现可直接替代 V4L2 的未公开厂商接口。
- 本地 ModelZoo、ATC、`.om` 和 Python API 资料。未发现可直接接入当前 Python 风险管线的已验证 SS928 NPU detector backend。

## 当前 USB 拓扑

- 左摄像头：`platform-10320000.xhci_1-usb-0:1.3:1.0-video-index0`
- 右摄像头：`platform-10320000.xhci_1-usb-0:1.4:1.0-video-index0`
- 两台设备 VID/PID 相同，序列号相同，`by-id` 会冲突，正式配置必须使用 `by-path`。
- 两台设备均工作在 480 Mbit/s USB 2.0 链路，并共享同一控制器/Hub。

## 同时 STREAMON 失败原因

UVC 驱动会在 `STREAMON` 时为周期传输预留总线带宽。同一 USB 2.0 路径上的两路摄像头声明了较高带宽，第二路预留失败后返回 `ENOSPC`。降低应用层读取频率不等于降低 USB 端点预留；本机摄像头还会把 MJPEG 5/10 FPS 请求协商回 30 FPS，因此不能用请求参数推断实际总线占用。

## 交替 STREAMON 的依据

调度器在启动目标侧前先停止当前侧，并在每次状态变更后检查最多只有一个设备处于 streaming。这样同一时刻只存在一路 UVC 带宽预留，避免第二路同时申请导致的 `ENOSPC`。切换顺序为停止当前侧、启动另一侧、丢弃预热帧、读取有效帧。失败重试有上限，退出路径会对两侧执行 best-effort `STREAMOFF` 并关闭 mmap/fd。

## 原生 V4L2 与 OpenCV 反复打开的差异

`v4l2_stream_toggle` 会保持两个设备 fd 和 mmap 缓冲，显式控制 `VIDIOC_STREAMON/OFF`；设备格式和缓冲只初始化一次。OpenCV `open/read/release` fallback 会反复创建和销毁完整 capture 对象，实际 backend、缓冲策略和释放时机不透明，切换时延通常更难解释。本轮只把原生实现标记为已验证，没有把 OpenCV fallback 伪装成原生切换。

## 预期盲区与风险

- 未激活侧只能显示最近缓存帧，不能称为实时或同步。
- 当前 500 ms 时间片下，实测最大单侧盲区约 0.51 至 0.54 秒。
- YOLO 推理时间会进一步扩大盲区；板端 C 阶段尚未验证。
- 单目测距、跟踪和风险状态必须按左右完全隔离。
- 未观测不等于 SAFE。状态只能在该侧再次观测时更新，或在明确的 stale timeout 后清除。
- controller 必须使用多帧稳定后的 `haptic_level`，不能使用 raw/visual risk。
- 风险优先只能延长危险侧时间片，不能让另一侧长期饥饿。

## 是否适合安全产品

不适合直接作为最终安全产品。该方案用时间复用换取 USB 可用性，天然存在盲区，且单 USB 控制器、单主进程和单模型构成共同故障点。更高安全等级应使用独立 USB 控制器、支持双路输入的 MIPI/ISP、硬件同步摄像头或经过验证的多传感器冗余。

## 阶段验收

- A：无同时 `STREAMON`、成功率至少 99%、两侧持续有帧、无永久卡死、退出后设备可重新打开。
- B：左右快照和状态可访问，未激活侧明确标记缓存帧及帧龄，客户端断开不影响采集。
- C：模型只加载一次，左右 tracker、轨迹、风险、稳定器、标定和日志完全独立，性能数据完整。
- D：只用稳定 haptic 状态驱动 PWM；切换不误清，陈旧观测最终清除，heartbeat 不写入 BLE 历史。

当前 A 的 2 分钟矩阵和 B 的 30 秒冒烟测试已通过；A 的 30 分钟连续验收、C/D 板端测试尚未完成，不能启用为默认模式。
