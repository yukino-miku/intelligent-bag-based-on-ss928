# SS928 双 USB 摄像头板端分析

更新日期：2026-07-16。本文件区分本地 `10_archive/ss928` 可确认的资料事实与当天通过 USB-UART 对真实开发板执行的只读验证；归档文件仍被 `.gitignore` 排除，不提交到 Git。

## 已审计资料

| 本地资料 | 读取内容 | 可确认结论 |
|---|---|---|
| `01.快速使用指南【必看】/产品规格书/海鸥派Euler Pi产品规格书V2.0.pdf` | 芯片和接口规格 | SS928V100、四核 Cortex-A55 1.4 GHz、4 GB LPDDR4X（可选 8 GB）、10.4 TOPS INT8 NPU、4 个 USB 3.0、双千兆网口、4K60 H.264/H.265 编码。 |
| `02.硬件连接与功能测试/海鸥派快速体验手册（例程验证）.pdf` | UVC、Wi-Fi、BLE、YOLO 章节 | 内核可枚举 `/dev/video0`；`sample_uvc --enum-formats` 可查格式；示例可采集 MJPEG。Wi-Fi 提供 STA/AP 脚本，Ubuntu/OpenEuler 说明中 dbus、bluetoothd 默认启动。 |
| `09.进阶功能开发/01.常用工具移植.zip` | Wi-Fi/蓝牙移植说明 | 提供 aarch64 构建说明、wpa_supplicant 2.10、hostapd 2.10、BlueZ 相关材料；不能据此认定当前镜像已经安装。 |
| `09.进阶功能开发/02.Opencv移植.zip` | OpenCV 4.5.5 源码/移植资料 | 平台有 OpenCV 移植路径；不代表当前 Python `cv2` 已安装。 |
| `09.进阶功能开发/04.Yolov8移植.zip` | Ultralytics/ATC/板端示例 | 主机侧可把模型转换为 `.om`；板端示例依赖厂商 NPU 动态库和特定 sample，示例输入链以 IMX347/MPP 为主。 |
| `09.进阶功能开发/06.Python调用海思API.zip` | pybind11、VPSS/Python/OpenCV/VO | 说明 Ubuntu 可安装 Python 3.10 开发包和 OpenCV，并展示 VPSS 帧送 Python；该示例依赖 MIPI/VO，不是当前双 UVC 方案。 |
| `在线仓库/SS928V100_SDK_V2.0.2.3_MPP_Sample-master.zip` | README、Makefile、`host_uvc.c`、VENC、RTSP、NPU YOLO | `host_uvc.c` 使用 V4L2 `VIDIOC_*` 枚举格式/尺寸/帧率和采集；VENC sample 支持 H.264/H.265/MJPEG；RTSP 库支持 H.264/H.265；NPU sample 加载 `.om`。 |
| `10.进阶综合案例/05.ModelZoo/model` | 模型目录 | 归档中确有 YOLO `.om` 文件，但模型许可、输入输出约定和与本项目类别/后处理的兼容性未确认，不迁移。 |
| `work/python_smoke_test` | Python 脚本和 README | 只读检查 `/etc/os-release`、CPU、温度、网络、`/dev/video*` 等；它不能证明双摄、推理或 Python 依赖已工作。 |

## 真实板端验证（2026-07-16）

| 项目 | 实测结果 | 结论 |
|---|---|---|
| 系统 | SS928V100，HiEulerPI V1.2，SDK V2.0.2.2；Ubuntu 22.04.1、Linux 4.19.90、aarch64、4 CPU | 系统和架构已确认，不再沿用资料推测。 |
| 内存/存储 | `free -m` 显示总内存 952 MiB、无 swap；根文件系统 29 GiB，已用约 1.7 GiB | 当前可用内存远低于产品规格书的 4 GB 版本描述，双 PyTorch detector 有明显 OOM 风险，必须实测后才能启用。 |
| 双 UVC 枚举 | 主采集节点为 `/dev/video0` 与 `/dev/video2`；`video1/3` 不是 capture 节点 | 两台摄像头均被内核识别，测试时无人占用。 |
| 稳定路径 | 两台设备均为 `0bda:3035` 且序列号同为 `200901010001`；by-id 冲突后只指向 `video2` | 当前硬件不能用 by-id 区分，必须固定物理口并使用两个不同的 by-path。 |
| USB 拓扑 | 两台相机分别在 `10320000.xhci_1` 下的 `3-1.1`、`3-1.3`，共同经过同一 USB 2.0 hub | 当前插法不满足“不同根控制器”，需要移动其中一台相机后复测。 |
| 格式枚举 | 两路均支持 MJPEG `640x480`、`1280x720`、`1920x1080` 等 30 FPS 描述符；`960x540` 不在枚举表。YUYV `640x480` 为 30 FPS，高分辨率更低 | `board_dual_balanced` 改用已枚举的 `640x480`，不依赖隐式分辨率回退。描述符 FPS 不等于实际持续 FPS。 |
| 单路取帧 | 使用 Python 标准库 V4L2 mmap 各测约 6 秒：`video0` 约 8.42 FPS，`video2` 约 7.46 FPS，收到的帧均有 JPEG SOI | 只证明 UVC 能真实出帧；没有 OpenCV 解码、YOLO、overlay 或长期稳定性。 |
| 双路取帧 | 并发 `640x480 MJPEG` 和 `320x240 MJPEG` 均有一侧 `VIDIOC_STREAMON: ENOSPC` | 当前 USB 接法不能通过双摄 preflight；不能宣称双路实时或稳定。 |
| 运行依赖 | Python 3.10.12、dbus、gi、BlueZ 可用；`cv2`、torch、ultralytics、lap、v4l2-ctl、FFmpeg、GStreamer、curl 和编译器缺失 | 板端视觉检测尚不能启动。板端当前无网络链路，不能在本轮通过 apt 在线补齐。 |
| 服务/温度 | `bluetooth.service` active，`smartbag.target` inactive；未发现可读 thermal zone | 未改板端服务；温度仍需找到厂商接口后验证。 |

上述 FPS 是一次短时、未解码的底层 UVC 诊断，不是视觉算法性能数据。临时探针只写入板端 `/tmp`，未安装系统包，也未覆盖 `/root/smartbag`。

## 能力边界

1. **操作系统**：当前实板已确认 Ubuntu 22.04.1/aarch64；其他板卡或镜像仍必须以板上 `cat /etc/os-release` 和 `uname -m` 为准。
2. **UVC/V4L2**：资料和实板都确认 USB UVC 枚举与采集能力。四个物理 USB 口不代表独立根控制器；当前同一 USB 2.0 hub 插法已经实测出现双路 `ENOSPC`。
3. **运行依赖**：归档给出了 Python、OpenCV、Wi-Fi、BlueZ 的安装或移植入口，但当前实板缺少视觉运行所需的 OpenCV、torch、Ultralytics 和 lap。部署脚本只检查或安装系统包，不自动假设 ARM wheel 可用。
4. **视频编码**：芯片和 MPP sample 有 H.264/H.265/MJPEG/RTSP 能力，但没有找到可直接接入现有 Python UVC detector 帧并供微信小程序播放的已验证接口。因此本轮先实现 JPEG snapshot 和 MJPEG HTTP 基线，不宣称硬件 VENC 已接入。
5. **NPU**：归档存在 ATC、`.om`、NPU 动态库和 C/C++ sample，证明平台有部署路径；没有找到与当前 `DetectorBackend`、Ultralytics `Results`、BoT-SORT 和风险链直接兼容的 Python API。`Ss928OmBackend` 继续明确报未实现，OpenVINO 也不等于 SS928 NPU。
6. **网络**：资料包含 Wi-Fi STA/AP 和双千兆网口。当前实现使用手机与板端可互访的 Wi-Fi/LAN，BLE 只传控制、状态和告警。

## 微信小程序网络限制

微信官方“网络”文档当前说明：小程序网络 API 通常只可与已配置的通信域名通信，正式域名使用 HTTPS/WSS；基础库 2.4.0 起允许访问局域网 IP，但真机行为仍受基础库、调试模式、证书、域名和平台差异影响。开发者工具可临时开启“不校验合法域名、TLS 版本及 HTTPS 证书”，这不等于正式环境可用。官方入口：<https://developers.weixin.qq.com/miniprogram/dev/framework/ability/network.html>。

因此本轮只确认：

- 浏览器可通过 `http://<BOARD_IP>:8080/` 验证双路 snapshot/MJPEG；
- 小程序实现 `SnapshotHttpTransport`，板端地址保存在本地 storage，不写死 IP；
- 游客 AppID、开发者工具和未配置合法域名的真机结果不能作为正式验收；
- 正式发布前必须使用实际 AppID，在目标 iOS/Android 微信版本上验证局域网 IP；若平台要求域名/HTTPS，则需要可解析域名、受信任证书和反向代理，不能使用自签名证书冒充完成。

## 本轮架构选择

每个 detector 是对应 USB 摄像头的唯一所有者：采集线程持续排空设备，容量为 1 的 latest-frame buffer 只交付新帧；同一进程完成推理、跟踪、风险、多帧稳定、raw/overlay 最新帧和按需 JPEG 编码。左右 detector 分别固定 `--side left` 与 `--side right`，各自维护 tracker、风险稳定器、CSV 和限流状态。

外部 `dual_camera_gateway.py` 只代理两个 detector 的 loopback HTTP 服务并汇总状态，不打开 `/dev/video*`。这样手机断开或慢速读取不会阻塞采集/推理，也不会出现第二个进程重复打开相机。

## 必须在真实硬件验证

```sh
cat /etc/os-release
uname -m
v4l2-ctl --list-devices
ls -l /dev/v4l/by-id/
v4l2-ctl --device /dev/video0 --list-formats-ext
v4l2-ctl --device /dev/video2 --list-formats-ext
lsusb -t
sh 09_deliverables/board_deploy/check-runtime-deps.sh
sh 09_deliverables/board_deploy/preflight.sh /etc/smartbag/config.json
```

仍需在把两台相机移到不同根控制器、补齐运行依赖并接通网络后记录：双路持续采集 FPS、双 detector 推理 FPS、CPU/内存/最高温度、Wi-Fi 吞吐、断开重连、PWM 物理方向和手机真机 snapshot 刷新。现有短时单路 UVC 数据不能外推为这些结果。
