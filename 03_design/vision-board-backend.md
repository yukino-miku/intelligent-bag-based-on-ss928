# 视觉板端后端设计

## 完整链路约束（2026-07-22）

正式数据流为 `UVC JPEG -> 每侧方向变换 -> DetectorBackend -> 统一 Detection -> 每侧独立 tracker -> StableTrackId -> CameraCalibration/CameraExtrinsics -> TrackState -> RiskModel -> RiskWarningStabilizer -> visual/haptic -> JSONL/CSV/overlay`。PC 与 SS928 的差异只能位于 DetectorBackend 和必要的输入转换，不维护第二份板端风险模型。

SS928 轻量 tracker 使用 class consistency、IoU、中心距离、真实 timestamp、时间型 lost buffer 和中心速度预测，服务于交替采集的不均匀间隔。它不是 BoT-SORT 的等价替代，必须通过同一录像的 ID switch、fragmentation 和 track lifetime 对比后才能评价精度。

production 模式只接受稳定 `by-path` 的 `video-index0`，左右必须解析为不同节点和不同 USB 设备。rotation/flip 在标定和检测之前执行，标定文件分辨率必须等于变换后分辨率。示例/diagnostic 标定不能用于正式测距风险输出。

`vision_only_validation` 是验收安全边界：controller 仍解析稳定后的 haptic 事件并写日志，但所有执行器、雷达、BLE 和其他传感器均禁用。正式输出恢复只能在视觉实景验收完成后进行。


`DetectorBackend` 统一 `predict()`、`track()`、类别名称和关闭接口。`UltralyticsBackend` 完整保留 PC 端 YOLO/BoT-SORT；`Ss928OmBackend` 通过窄 C ABI 调用 SS928 ACL，把 USB BGR 帧在内存中转换为模型要求的 RGB planar tensor，并解析固定 `1x84x8400 FP32` 输出。NPU 后端不依赖 torch、Ultralytics 或临时图片文件。

两种后端都继续进入同一套单目测距、稳定 ID、速度、Future Conflict Gate、多帧稳定、self-object filter、visual/haptic 分层、CSV 和 overlay。NPU 路径使用轻量 IoU tracker，交替双摄左右 tracker 与风险状态完全独立；`.om` 模型只加载一次并在进程内常驻。

`board_cpu` 仍是通用 CPU 基线。正式 NPU 配置使用 `detector_backend=ss928_om`、固定模型输入 `640x640`、`conf=0.08`、`max_det=30`。OpenVINO 不等于 SS928 NPU；模型 tensor 契约不匹配时后端必须拒绝启动。
