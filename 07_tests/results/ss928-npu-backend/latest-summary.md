# SS928 NPU 正式后端验收摘要

日期：2026-07-21

## 结论

- `LOCAL IMPLEMENTED`：USB BGR 内存帧、SS928 ACL/NPU、YOLO 后处理、轻量 tracking、原有距离/速度/风险、多帧稳定和 overlay 已接成同一条代码链。
- `ARM64 CROSS-BUILT`：`libsmartbag_ss928_acl.so` 已重编译为 aarch64 ELF shared object，SHA256 为 `00a496a6576f2f8473274878535715dfe47697b5f33692c4203f5ec913fdbe9d`。
- `NOT BOARD VERIFIED`：本轮结束前板端 SSH、HTTP 和 USB 串口均不可达，未执行真实双摄连续 NPU、现场目标命中或 overlay 验收，不能标记 BOARD TESTED。

## 已验证链路

```text
USB/OpenCV or native V4L2 frame
  -> RGB planar letterbox in memory
  -> persistent SS928 .om model through ACL C ABI
  -> FP32 1x84x8400 decode + class filter + class-aware NMS
  -> side-local lightweight IoU tracker
  -> StableTrackId + TrackState + monocular distance/speed
  -> Future Conflict Gate + RiskModel + multi-frame stabilizer
  -> visual/haptic levels + risk CSV + overlay/JPEG gateway
```

模型、ACL input/output dataset 和 device buffers 在 detector 进程内常驻。模型契约不满足 RGB 图像输入、COCO 80 类和 FP32 `1x84x8400` 输出时拒绝启动。NPU 路径不依赖 torch、torchvision、Ultralytics 或 lap。

## 本地验证

- `python -m unittest discover -v`：293 项，292 通过，1 项 Windows 上跳过的 Linux `fcntl` 进程锁测试。
- `python -m compileall`：通过。
- 小程序：6 个 JavaScript 测试文件通过，24 个 JavaScript 文件语法通过。
- 受控配置：22 个 tracked JSON 解析通过。
- 部署脚本：39 个 shell 文件通过 `sh -n`。
- 仓库硬件刷新策略和 `git diff --check`：通过。
- NPU 定向测试覆盖 RGB/CHW 预处理、类别过滤、NMS 坐标恢复、错误 tensor 契约拒绝、左右 tracker 隔离，以及 fake NPU 输出进入 tracking/risk/overlay。

## 本轮板端连接结果

- PC 有线地址为 `192.168.1.10/24`。
- `192.168.1.102` 和 `192.168.1.168` 的 SSH、HTTP 80、8080、8081 均无响应；ping 也未返回。
- Windows 当前只枚举蓝牙 COM5/COM6，没有板端 USB-UART COM 口。
- 因此没有停止现有摄像头进程、覆盖生产目录、enable systemd 或启动执行器。

## 恢复连接后的板端门禁

1. 核对 `/opt/lib/npu/libascendcl.so`、`yolov8n.om`、Python OpenCV/NumPy和两侧最新 `/dev/v4l/by-path`。
2. 安装交叉编译 adapter 后运行 `check-runtime-deps.sh` 和 `alternating-preflight.sh`。
3. 先以 60 秒临时 session 运行 `alternating_dual_camera_tracker.py --detector-backend ss928_om`，确认模型仅加载一次、左右都有真实 overlay、ID 不串侧。
4. 检查 `performance.csv` 中 preprocess/NPU/postprocess/tracking/risk/overlay/JPEG 和 E2E gap，再进行 30 分钟稳定性、断线恢复、内存和温度验收。
