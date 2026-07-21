# 视觉板端后端设计

`DetectorBackend` 统一 `predict()`、`track()`、类别名称和关闭接口。`UltralyticsBackend` 完整保留 PC 端 YOLO/BoT-SORT；`Ss928OmBackend` 通过窄 C ABI 调用 SS928 ACL，把 USB BGR 帧在内存中转换为模型要求的 RGB planar tensor，并解析固定 `1x84x8400 FP32` 输出。NPU 后端不依赖 torch、Ultralytics 或临时图片文件。

两种后端都继续进入同一套单目测距、稳定 ID、速度、Future Conflict Gate、多帧稳定、self-object filter、visual/haptic 分层、CSV 和 overlay。NPU 路径使用轻量 IoU tracker，交替双摄左右 tracker 与风险状态完全独立；`.om` 模型只加载一次并在进程内常驻。

`board_cpu` 仍是通用 CPU 基线。正式 NPU 配置使用 `detector_backend=ss928_om`、固定模型输入 `640x640`、`conf=0.08`、`max_det=30`。OpenVINO 不等于 SS928 NPU；模型 tensor 契约不匹配时后端必须拒绝启动。
