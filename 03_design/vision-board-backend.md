# 视觉板端后端设计

`DetectorBackend` 统一 `track()` 和名称读取接口。`UltralyticsBackend` 完整保留现有 YOLO/BoT-SORT、测距、Future Conflict Gate、多帧稳定、self-object filter、visual/haptic 分层和 CSV 日志。`Ss928OmBackend` 目前仅声明边界并抛出可解释错误；没有真实 API 前不返回伪检测结果。

`board_cpu` 初始参数为 640x480、imgsz 416、conf 0.06、max_det 30。它用于验证协议和板端 CPU 基线，不等同于 NPU 性能目标。
