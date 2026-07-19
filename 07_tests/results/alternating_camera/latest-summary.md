# 交替双摄最新验证摘要

日期：2026-07-19
分支：`agent/alternating-dual-camera`
正式默认：`fixed_dual_process`，`alternating_camera.enabled=false`

## 30 分钟纯采集验收

真实板端 session：`20260719-112904_ss928_v4l2_640x480_30fps`

| 项目 | 结果 |
|---|---:|
| 运行时长 | 1800.247 s |
| 切换 | 3620 / 3620，100.0% |
| 左/右有效帧 | 7240 / 7240 |
| 左/右有效 FPS | 4.022 / 4.022 |
| 请求/实际格式 | 640x480 MJPEG @30 / 640x480 MJPEG @30 |
| 切换 p50/p95/p99 | 252.404 / 275.332 / 283.061 ms |
| 首帧 p50/p95/p99 | 68.058 / 68.259 / 68.320 ms |
| capture-only p50/p95/p99 | 489.126 / 519.877 / 569.307 ms |
| capture-only 最大盲区 | 580.264 ms |
| ENOSPC | 0 |
| STREAMON/OFF 失败 | 0 / 0 |
| 首帧超时、丢帧、相机错误 | 0 / 0 / 0 |
| CPU 平均/峰值 | 2.960% / 7.716% |
| 进程 RSS 平均/峰值 | 30.471 / 33.539 MiB |
| 系统已用内存平均/峰值 | 123.997 / 129.445 MiB |
| 温度 | `null`，板端未找到可读温度节点 |
| 进程重启 | 0 |

capture-only 分位数由 3620 条原始 switch 记录按“每次切换左右盲区较大值”计算；代码现已把 p50/p95/p99 写入后续 summary。性能 CSV 第一条到最后一条的 RSS 为 27.238 -> 33.539 MiB，增加 6.301 MiB；系统已用内存为 120.754 -> 127.242 MiB，增加 6.488 MiB。该 session 使用修复前的无界诊断列表。随后在 `0d8f8c2` 中把 switch、performance、E2E 和阶段计时改为有界 deque，并用独立累计量保留精确总数、均值和峰值；本地回归覆盖窗口淘汰后汇总总数仍正确。尚未用修复后的代码再跑第二个 30 分钟 session，因此不能宣称内存增长已完成实板复验。

原始 session 已保存到 Git 忽略路径 `08_media/alternating_camera_runs/20260719-112904_ss928_v4l2_640x480_30fps.tar.gz`，压缩包 SHA256：`7F076DD52647FD97C73581B7D6F8BE7408985061FCF1E86A542479E010F0A523`。原始 CSV、日志和 tar 不提交 GitHub。

## 网关和断连恢复

- `20260719-120958_ss928_v4l2_640x480_30fps`：板端本机 `127.0.0.1:8081` 的 status/cameras/左右 status 均 HTTP 200；左右 raw 在正常、另一侧 unbind 和恢复后均 HTTP 200。无模型模式下左右 overlay 均按设计返回 HTTP 503，不能当作检测框通过。
- 同一 session 通过 sysfs 对 USB 设备 `3-1.3` 和 `3-1.4` 分别执行逻辑 unbind/rebind。左、右恢复耗时分别 3023.537 ms、2998.492 ms；另一侧在故障期间继续采集，恢复后双侧回到约 4 FPS。该操作不是人工物理拔线。
- 该故障注入 session 因预期的失败切片只有 170/182 成功，程序按验收规则退出码为 2；不是进程崩溃。它暴露出 summary 的 reconnect 总数未按侧汇总，已在 `38c4a91` 修复。
- 修复后 session `20260719-121409_ss928_v4l2_640x480_30fps`：50.205 s，左侧一次逻辑断连后 1717.290 ms 恢复，summary 正确记录 `camera_reconnects=1`，101/104 切片成功，无 ENOSPC，结束后 `/dev/video0` 和 `/dev/video2` 无占用。
- 更早的 `20260719-120811_ss928_v4l2_640x480_30fps` 是失败测试：网关尚未就绪就注入断连，并受默认 `--switch-count 20` 提前结束。记录保留，不作为通过证据。

## 已通过的软件验证

- 本地 `python -m unittest discover -v`：229 项通过。
- 交替采集测试覆盖单 STREAMON 不变量、最新帧有界选择、跨侧独立状态、重连、网关 raw/overlay 分离、跨 slice 风险确认和 session 精确汇总。
- PC 冒烟只初始化一个 Ultralytics YOLO 实例；左右 BoT-SORT、StableTrackId、TrackState、RiskModel、stabilizer、标定和日志对象互相独立。
- GitHub Actions 已覆盖 compileall、Python unittest、JSON、JS、小程序、shell、仓库大文件/媒体/模型策略和 PR diff 检查。

## 依赖和模型状态

- 板端：Python 3.10.12；`cv2`、`numpy`、`torch`、`torchvision`、`ultralytics`、`lap`、`pip` 均未安装。
- APT 缓存显示候选版本 NumPy 1.21.5、OpenCV 4.5.4、pip 22.0.2，但板端 `eth0 linkdown`、无 DNS。带 45 秒超时的 `apt-get update` 返回码 124，错误为 `Temporary failure resolving 'mirrors.tuna.tsinghua.edu.cn'`。
- 本地 `10_archive` 未找到 cp310/linux_aarch64 wheelhouse，因此没有可报告的 wheel SHA256，也没有尝试盲装最新版 Ultralytics。
- 板端存在 `/opt/sample/yolov8/yolov8n.om`，大小 7,932,770 bytes，SHA256 `7010D928C2CE9675EA38B6EE353F1C4FCD4EC648A335D3735D85F2E0313D030B`；存在 `/opt/lib/npu/libascendcl.so`。现有 sample 绑定 sensor/MPP，缺少当前 USB 内存帧、预处理/AIPP、输出/NMS 和 Python tracker 风险链的已核对通用 API，不能据此宣称 OM 后端可用。

## BLOCKED

- **完整 E2E 盲区**：30 分钟 session 是纯采集，`end_to_end_*` 为 0/null。未运行 YOLO、tracker、风险、overlay 和 JPEG，因此只有 capture-only 数据。
- **旧 session 的 selected 字段**：A6 使用修复前入口，`selected_inference_frames=14480` 只是当时 `record_frame()` 的默认标记，并不表示发生了推理；代码现已对无模型入口明确写 `selected_for_inference=false`。
- **板端模型**：视觉依赖未安装，模型加载次数、加载耗时、单帧推理时间、推理 FPS 和模型运行峰值 RSS 均为 N/A。
- **检测框 overlay**：raw 已板端 HTTP 验证；overlay 无模型时为 503。未验证带框左右 overlay，也无法从 PC 浏览器访问，因为当前只有 USB-UART，没有可用网络链路。
- **风险与跨 slice 实物链**：自动化测试通过；本次板端 session 无模型，风险等级计数、跳变抑制、fast path 和真实告警均为 0，不能作为实物风险验证。
- **PWM/电机**：只确认 `/sys/class/pwm/pwmchip0`、`pwmchip16` 存在且各 `npwm=16`。未在未知接线状态下驱动真实电机，告警到 PWM 延迟和 camera disconnect clear 的物理闭环为 N/A。
- **BLE/小程序**：`bluetoothctl` 存在但 Bluetooth service 为 inactive；未连接手机。BLE alert、SYS STATUS、GNSS/IMU 路由和微信真机均未验证。
- **物理拔插**：只完成 sysfs 逻辑 unbind/rebind；人工拔线、重新插入不同物理口和长时间反复拔插仍未验证。
- **修复后完整长测**：有界遥测代码尚未再跑 30 分钟，完整视觉链 30 分钟也未运行。

结论：30 分钟纯交替采集通过，双侧逻辑断连恢复通过，板端本机 raw 网关通过；完整视觉、overlay、PWM、BLE、小程序和 E2E 盲区仍为 BLOCKED。实验模式继续默认关闭，不能替代正式模式，也不能称为同步双摄。
