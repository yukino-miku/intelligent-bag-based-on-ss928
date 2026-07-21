# SS928 NPU 正式后端验收摘要

日期：2026-07-21

## 结论

- `BOARD FUNCTIONAL PASS`：板端 USB 帧、静态 AIPP NV12 预处理、SS928 ACL/NPU、YOLO 后处理、轻量 tracking、原有距离/速度/风险、多帧稳定和 overlay 已在同一进程中连续运行。
- `CAMERA IMAGE BLOCKED`：当前 `/dev/video0` 和 `/dev/video2` 返回的 JPEG 近乎全黑，因此没有现场目标命中、检测框准确性或风险等级实景证据，不能把本次短测记为完整视觉验收通过。
- `SHORT RUN ONLY`：84.425 秒短测 99/99 次切换成功，但完整 E2E 最大间隔 1272.578 ms，略高于 1200 ms 门限；尚未执行修正后的 30 分钟稳定性验收。
- ARM64 `libsmartbag_ss928_acl.so` SHA256：`00a496a6576f2f8473274878535715dfe47697b5f33692c4203f5ec913fdbe9d`。

## 已验证链路

```text
USB native V4L2 MJPEG frame
  -> OpenCV decode and letterbox
  -> NV12 for the board model static AIPP
  -> persistent SS928 .om model through ACL C ABI
  -> FP32 1x84x8400 decode + class filter + class-aware NMS
  -> side-local lightweight IoU tracker
  -> StableTrackId + TrackState + monocular distance/speed
  -> Future Conflict Gate + RiskModel + multi-frame stabilizer
  -> visual/haptic levels + risk CSV + overlay/JPEG gateway
```

模型、ACL input/output dataset 和 device buffer 在 detector 进程内常驻。后端按 ACL 的逻辑维度、数据类型和实际字节数区分普通 RGB tensor 与静态 AIPP NV12 tensor。当前板载模型的输入元数据为逻辑 `1x640x640x3 UINT8`、物理 614400 bytes，输出为 `1x84x8400 FP32`、2822400 bytes。NPU 路径不依赖 torch、torchvision、Ultralytics 或 lap。

## 板端环境和安装

- SS928V100，Ubuntu 22.04.1，aarch64，Linux 4.19.90。
- PC 有线地址 `192.168.1.10/24`；板端可通过 `192.168.1.102` 和 `192.168.1.168` 到达，本次 SSH 使用 `.102`。
- 模型：`/opt/sample/yolov8/yolov8n.om`，SHA256 `7010d928c2ce9675ea38b6ee353f1c4fcd4ec648a335d3735d85f2e0313d030b`。
- ACL：`/opt/lib/npu/libascendcl.so`。
- 离线安装 NumPy 1.26.4 和 opencv-python-headless 4.10.0.84；测试目录为 `/root/smartbag-npu-fa77ea3`。
- 两路稳定物理路径分别对应 USB `1.3` 和 `1.4` 的 `video-index0`；`video-index1` 不是 V4L2 capture 节点。
- 只测试摄像头和视觉 NPU。未启动 PWM、TM6605、BLE、GNSS、IMU、雷达或音频。

## 真实短测结果

Session：`20260721-034313_ss928_single-model_640x480_30fps`

| 指标 | 结果 |
|---|---:|
| 运行时长 | 84.425 s |
| 切换成功 | 99 / 99 |
| 左/右有效帧 | 50 / 49 |
| 选中推理帧 | 99 |
| 合计推理 FPS | 1.644 |
| preprocess | 约 2.9 ms |
| NPU execute | 约 25.66 ms |
| postprocess | 约 17.2 ms |
| detector 总耗时 | 约 81.1 ms |
| tracking / risk | 约 0.25 / 0.15 ms |
| overlay / JPEG | 约 7.18 / 6.77 ms |
| E2E p95 / max | 1219.665 / 1272.578 ms |
| capture-only max | 683.816 ms |
| CPU 平均 / 峰值 | 14.403% / 15.556% |
| RSS 平均 / 峰值 | 115.916 / 115.980 MiB |
| STREAMON/OFF/首帧错误 | 0 / 0 / 0 |

`/api/v1/status` 明确报告 `model_backend=ss928_om`，左右 raw 和 overlay 端点均返回 JPEG。板端 ACL 启动会打印缺少通用 AICPU kernel SO 的日志，但该 YOLO 模型仍正常加载、执行并释放；本次没有出现旧临时 harness 的 `aclFinalize()` 退出崩溃。

## 摄像头黑帧证据

- 左右 raw JPEG 解码后均约为 mean 1.67，像素范围约 0-6；overlay 只有白色状态文字，底图仍黑。
- `/dev/video0` 和 `/dev/video2` 连续各读 8 帧仍黑；左侧连续读 50 帧约 6.6 秒仍黑，不是只取首帧造成的预热问题。
- 两节点均协商为 640x480 MJPEG，`/dev/video1` 和 `/dev/video3` 明确不是 capture 节点。
- Brightness、Contrast、Gain、Exposure Auto 等 V4L2 控制可读且接近默认值，没有枚举到启用的 privacy 控制。
- 因为 detector 接收到的原始 JPEG 已经黑，问题位于当前摄像头物理输入、遮挡、供电或设备状态，不是 NPU、overlay 或网络传输把图像变黑。

## 本地验证

- `python -m unittest discover -v`：296 项，295 通过，1 项 Windows 上按预期跳过的 Linux `fcntl` 进程锁测试。
- 新增测试覆盖静态 AIPP NV12 元数据识别、Y/UV 排列、输入字节数和 fake NPU 推理；原 RGB CHW 路径继续通过。
- 既有 compileall、小程序 JavaScript、JSON、shell、仓库策略和 whitespace 检查在上一提交已通过；本次变更未修改这些接口。

## 后续门禁

1. 先恢复两路相机的非黑原始画面，再复跑同一短测并放置 car/bicycle/motorcycle/bus/truck 实物或测试画面。
2. 完成左右相机独立内参、畸变、安装外参和 pitch 标定；当前只使用 diagnostic 占位标定，不能验收距离和风险数值。
3. 在实景目标下核对左右 ID 不串侧、检测框、距离、Future Conflict、visual/haptic 分层和 risk CSV。
4. 调整切片参数，使完整 E2E max 稳定低于 1200 ms，再运行至少 30 分钟和断线恢复验收。
