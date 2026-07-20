# SS928 板端整合状态

## 2026-07-20 Rev2 硬件刷新

- `LOCAL IMPLEMENTED`：autonomous 分支默认改为单模型交替双摄、0–4 四档触觉、有界持续灯光/音频、固定 venv、systemd controller/safe-off/boot-selftest 和完整 validation orchestrator。
- `BOARD NOT RUN`：用户要求本轮先不执行板端烧录，因此没有上传、enable、执行器通电、断开电脑或两次重启证据；`POWER_ONLY_AUTOSTART_NOT_READY`。
- `IMPLEMENTED + UNIT TESTED`：TCA9548A 统一事务、BMI270 CH0、左右 TM6605 CH1/CH2、灯光调度、MR20 解析/replay、来源隔离融合、Rev2 OutputPolicy、Cloud uploader 和 Cloud 安全核心。
- `REPLAY TESTED`：匿名化 MR20 0x60A/0x60B 样例连续两 scan 后才形成 `radar:right_rear` 候选等级；未知帧和错误来源被统计且不报警。
- `NOT DEPLOYED`：CloudBase 云函数和数据库集合；仓库不含 EnvId、AppID、设备密钥或 HMAC secret。
- `BLOCKED`：真实 TCA9548A/BMI270/TM6605、左右灯光、MR20 0x60B 移动目标、雷达到执行器/BLE 闭环、30 分钟联合运行。2026-07-20 收尾时 Windows 未枚举板端 USB 串口/USB 网卡且 SSH 不可达，没有实物日志前不标记 PHYSICALLY VERIFIED。
- 视觉风险算法没有被雷达代码改写。vision、radar、manual 独立稳定并按同侧最大值输出；一个来源退出、clear 或 stale 不会误清另一个来源。

## 已完成

- 默认改为 `alternating_single_model`：原生 V4L2 单 active side、单次模型加载、左右独立 tracker/risk/标定/CSV、稳定 haptic 风险优先调度和 session 报告。
- 每片默认只选最后 1 张最新有效帧推理，无积压队列；新增 capture-only 与完整 E2E 两套盲区、跨侧延迟和全阶段 monotonic 时间戳。验收优先使用 `end_to_end_max_gap_ms`。
- CAUTION/DANGER/EMERGENCY 的普通确认必须跨独立 `slice_id`；单 burst 不能直接满足 DANGER，紧急 fast path 有严格质量条件和原因日志。tracker 可按每侧真实有效 FPS 调整时间缓冲。
- 交替 detector 内部直接提供左右 raw/overlay snapshot、MJPEG、完整状态 API 和双画面浏览器页，不启动第二个摄像头所有者；HTTP access log 默认关闭。
- 单侧断线状态机实现 close/unmap、有限指数退避、reopen/remap、恢复耗时和按断线时长重置本侧 tracker；另一侧不重置。硬件拔插闭环仍待实测。
- 新增左右安装外参、背包坐标转换、production 标定检查器和 camera/backpack 风险日志字段；示例仍是 `calibrated=false` 占位，不能用于正式距离风险验收。
- Controller 已区分 `state_change` 与 `heartbeat`；切换相机不把未观测侧当成 SAFE，heartbeat 不进入 BLE 历史，stale observation 或单进程 detector 退出会清除对应/全部 PWM 状态。
- 正式 systemd 使用 `smartbag.target -> smartbag-controller.service`；controller 内部监督 alternating detector，配置拒绝左右指向同一真实设备。
- 每个 detector 是相机唯一所有者，使用容量 1 latest-frame buffer、有限断流重连、独立 tracker/RiskModel/stabilizer/CSV 和稳定 haptic JSONL。
- 左右 PWM 独立；单侧 level=0、超时或 detector 退出只清对应侧，子进程有限退避重启，另一侧继续。
- 双路 snapshot/MJPEG、聚合状态、浏览器调试页和按需 JPEG；BLE 不传视频。
- 微信小程序双摄页使用 completion-driven refresh、每侧单 in-flight、生命周期停止、指数退避和单侧聚焦降频；地址继续存 storage，不写死板端 IP。
- GNSS/BMI 默认不注册 BLE；统一设备名为 `SS928-SmartBag`。
- 双标定模板、依赖/相机/preflight/stream/模拟双视频脚本和部署文档已齐全。
- 本地 229 项 Python 测试、4 个小程序测试文件和 compileall/JSON/JS/shell/diff 检查通过；GitHub Actions 已加入相同的轻量检查和仓库大文件/媒体/模型策略。

## 真实开发板已验证（更新至 2026-07-19）

- USB-UART 登录确认 SS928V100、Ubuntu 22.04.1/aarch64、Linux 4.19.90、4 CPU；当前总内存仅 952 MiB、无 swap。
- 两台 `0bda:3035` UVC 相机分别枚举为 `/dev/video0`、`/dev/video2`，但序列号相同导致 by-id 冲突，只能用不同 by-path 固定物理口。
- 两台相机当前共同挂在 `10320000.xhci_1` 的 USB 2.0 hub 下。标准库 V4L2 mmap 单路短测约 8.42/7.46 FPS；双路 640x480 和 320x240 均有一侧 `ENOSPC`，当前接法未通过双摄验收。
- 当前镜像的 Python 3.10.12 缺少 `cv2/numpy/torch/torchvision/ultralytics/lap/pip`；APT 有 NumPy 1.21.5、OpenCV 4.5.4 和 pip 候选，但 `eth0 linkdown` 且 DNS 不通，45 秒 APT 更新超时；本地也没有 cp310/aarch64 wheelhouse。
- 原生 `v4l2_stream_toggle` A1-A4 每组约 2 分钟，总计 989 次切换全部成功，无 ENOSPC/首帧超时；p95 切换 273.726-278.018 ms，最大单侧盲区 539.016 ms，左右有效约 4.08-4.13 FPS。
- B 阶段缓存双画面 status、左右 snapshot 和浏览器页均返回 HTTP 200；gateway 不重新打开摄像头，退出后 `/dev/video0`、`/dev/video2` 均无占用。
- 30 分钟纯采集 session `20260719-112904_ss928_v4l2_640x480_30fps` 运行 1800.247 s，3620/3620 切换成功，左右各 7240 帧、4.022 FPS，无 ENOSPC/STREAMON/OFF/首帧超时；capture-only 最大盲区 580.264 ms，RSS 平均/峰值 30.471/33.539 MiB，温度仍为 null。
- 左右 sysfs 逻辑 unbind/rebind 均恢复，约 3.024/2.998 s；另一侧继续采集，raw HTTP 保持 200。修复 reconnect 汇总后复测正确记录 `camera_reconnects=1`。物理拔插仍未验证。
- 长测使用修复前的无界诊断列表，RSS 首末增加 6.301 MiB；随后已改为有界 deque 和精确累计量，但修复后的第二个 30 分钟 session 尚未执行。

## 仍需真实硬件验证

- 当前板上没有额外独立 USB 根端口；若要真正并发双摄，需要外接独立控制器或改 MIPI。现有交替方案仍需左右真实拔插恢复测试。
- 通过联网 apt 或经过 ABI 验证的离线 aarch64 包补齐 OpenCV/torch/ultralytics/lap，再验证模型加载。
- `board_dual_balanced` 双 detector 的 capture/inference/stream FPS、CPU、内存、最高温度和 30 分钟以上稳定性；当前只有未解码的短时 UVC 数据。
- `alternating_single_model` C 阶段的板端模型加载、双侧检测、真实推理盲区、RSS/CPU/温度，以及 D 阶段左右 PWM、heartbeat、stale clear 和 BLE 历史。
- 左右独立相机内参、畸变、高度、pitch、朝向和风险日志实景校准。
- PWM sysfs 编号、四路物理方向、电机驱动供电、单侧退出清振和紧急停止。
- BlueZ NUS、自动 alert、GNSS/IMU/SYS 往返；手机真机 snapshot、局域网/HTTPS/合法域名限制。
- DX-GP21 UART4、BMI270 IIO/I2C、MAX98357；Rev2 音频默认启用但 optional，缺失时必须降级而不能阻断视觉和触觉。

## 未完成

- `Ss928OmBackend` 没有与现有 Python detector、BoT-SORT 和风险链兼容的真实厂商 API。归档仅证明存在 ATC、`.om` 和 C/C++ sample；OpenVINO 不是 SS928 NPU。
- 板端 `/opt/lib/npu/libascendcl.so` 和 sensor 专用 `yolov8n.om` sample 不能直接消费当前 USB 内存帧；缺少匹配头文件、通用 C ABI、预处理/AIPP 和输出/NMS核对，因此未伪造后端。
- MPP VENC/RTSP 尚未接入当前 UVC detector 帧。当前交付是 CPU JPEG snapshot/MJPEG 基线，不宣称硬件 H.264/H.265 已完成。
- 微信小程序真机和正式 AppID/HTTPS/合法域名尚未验证；浏览器页是当前独立板端视频验收入口。
