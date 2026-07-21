# PC 到 SS928 视觉一致性审计

审计日期：2026-07-22。板端实测列只记录本轮可确认的证据；无法连接板端时不沿用旧结果冒充本轮通过。

| 功能 | PC 入口 | SS928 入口 | 共享代码 | 单元测试 | 本轮板端实测 | 差异/说明 |
|---|---|---|---|---|---|---|
| 模型预处理 | `UltralyticsBackend` | `Ss928OmBackend` | 否，backend 边界 | 是 | 阻塞 | SS928 支持 AIPP NV12 与 RGB tensor |
| 模型推理 | PyTorch/OpenVINO | ACL/NPU `.om` | 否，backend 边界 | fake runtime | 阻塞 | 不把 OpenVINO 当作 SS928 NPU |
| 输出解码/NMS | Ultralytics | `decode_yolo_84x8400` | 统一 Detection 语义 | 是 | 阻塞 | SS928 严格校验 `1x84x8400 FP32` |
| 类别过滤 | `target_class_ids_from_model_names` | 同一函数和 COCO 映射 | 是 | 是 | 阻塞 | 默认保留 person 及五类交通目标 |
| bbox 坐标恢复 | ROI helper | 同一 helper | 是 | 是 | 阻塞 | 恢复后才进入标定和风险 |
| tracker | BoT-SORT/ByteTrack | 时间感知 NumPy IoU tracker | 接口一致，算法不同 | 是 | 阻塞 | 轻量 tracker 不宣称等价 BoT-SORT |
| 左右 ID 隔离 | 独立 tracker context | 独立 tracker context | 是 | 是 | 阻塞 | 单个 detector model，不共享 tracker |
| StableTrackId | `StableTrackIdManager` | 同一类 | 是 | 是 | 阻塞 | 二次稳定关联 |
| 畸变/内参 | `CameraCalibration` | 同一类 | 是 | 是 | 阻塞 | production 硬校验分辨率和方向 |
| 相机到背包坐标 | `CameraExtrinsics` | 同一类 | 是 | 是 | 阻塞 | x 向右、z 向前 |
| 单目距离 | `estimate_ground_point_from_bbox` | 同一函数 | 是 | 是 | 阻塞 | 实测误差尚无本轮证据 |
| 速度/方向 | `TrackState` | 同一类 | 是 | 是 | 阻塞 | 使用真实 monotonic capture 时间 |
| approaching/moving-away | Risk/TrackState | 同一代码 | 是 | 是 | 阻塞 | 不以单帧速度跳变直接输出 |
| corridor/CPA | `risk_model.py` | 同一文件 | 是 | 是 | 阻塞 | 有限时间 Future Conflict Gate |
| 风险评分与 0..4 | `RiskModel` | 同一类 | 是 | 是 | 阻塞 | 未建立 board_risk_model 分叉 |
| 多帧确认 | `RiskWarningStabilizer` | 同一类 | 是 | 是 | 阻塞 | 保留升级确认和降级迟滞 |
| 跨 slice 确认 | 稳定器 slice 字段 | 同一类 | 是 | 是 | 阻塞 | haptic 不能由同一 burst 单帧绕过 |
| self-object filter | `SelfObjectFilter` | 同一类 | 是 | 是 | 阻塞 | 画面底部自身前景不触发震动 |
| stale/camera clear | `AlertJsonlEmitter` | 同一类 | 是 | 是 | 阻塞 | 断线和退出发 level 0 |
| overlay | `draw_overlay` | 同一函数 | 是 | fake NPU E2E | 阻塞 | gateway 只消费缓存帧，不重开相机 |
| JSONL | `AlertJsonlEmitter` | 同一类 | 是 | 集成测试 | 阻塞 | stdout 只输出单行事件，日志进 stderr |
| CSV/session | Risk CSV | Risk CSV + 完整 session CSV | 风险字段共享 | 是 | 阻塞 | 新增 detection/track/distance/risk 明细 |
| gateway | PC OpenCV window/文件 | `AlternatingCameraGateway` | overlay 共享 | 是 | 阻塞 | 浏览器断开不应停止检测 |
| controller alert | JSONL | JSONL 子进程 | 同一协议 | 是 | 阻塞 | 只消费稳定后的 haptic level |

结论：风险和测距测速核心没有拆成 PC/板端两套实现；允许差异仅位于 detector backend 和 SS928 必要的图像输入转换。真实等价性仍需同一录像与实板 session 对比。
