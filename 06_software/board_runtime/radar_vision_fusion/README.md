# 雷达主导的视觉车型融合

正式模式 `radar_primary_visual_classification` 由 MR20 提供目标位置和速度，两只 USB 摄像头交替获取车型快照，一个 YOLO/OM 实例完成检测。视觉不做 BoT-SORT、单目测距、测速或风险计算；最终风险仍复用 `vision_obstacle_tracker/risk_model.py`，但以雷达运动量为输入。

## 正式数据流

```text
MR20 0x60A/0x60B -> 完整性组包 -> RadarTrackManager
                                      |
                                      +-> 每次雷达观测计算 RiskModel 样本
                                      +-> 每轨迹固定 0.5 s 中位数 -> 每侧 haptic level

左/右 UVC -> 单路 STREAMON -> 一张新鲜快照 -> 单 YOLO
                                      |
                                      +-> 水平区间重合 + Hungarian
                                      +-> 原子替换该侧 LatestVisualClassMap
```

融合内部没有混合 `RadarScan` 和 `ClassificationFrame` 的共享队列。雷达和相机回调直接在锁保护下更新最新状态；Controller 最终接收 `AlertEvent` 的队列仍保留。相机或模型失效不会阻塞雷达，车型按 `unknown` 处理。

## 模块

- `v4l2_snapshot_camera.py`：Linux 原生 V4L2 fd/mmap 预分配，短周期 STREAMON/DQBUF/STREAMOFF。
- `alternating_snapshot_classifier.py`：左右约 0.20 s 相邻启动目标、单模型、故障隔离和 p50/p95/max 指标。
- `radar_tracks.py`：雷达 generation、安装变换、历史趋势和质量指标；不完整扫描不会漏记或删除其他轨迹。
- `radar_vision_association.py`：雷达投影水平容差区间、bbox 扩展区间、时间/中心/弱尺寸代价、Hungarian 一一分配和歧义拒绝。
- `median_risk.py`：每个 `radar_track_key` 独立、互不重叠的 0.5 s 风险中位数窗口。
- `runtime_settings.py`：运行参数白名单、范围校验、原子应用和 `/etc/smartbag/runtime-tuning.json` 持久化。
- `alert_history.py`：三级/四级事件去重和同侧快照，保存到 `/var/lib/smartbag/alarm-events`。
- `fusion_runtime.py`：最新状态融合、每图车型映射替换、风险窗口和 Controller 输出。
- `fusion_debug_server.py`：状态、参数、告警历史和调试 JPEG HTTP API，不参与风险计算。
- `visual_binding.py`：仅保留给 `legacy_dual_vision` 回归，正式模式不调用。

MR20 的 `0x60B` 目标帧不携带独立 measurement count，因此组包只能由前导 `0x60A` 的目标数和相邻 `0x60A` 序列校验。序列跳变、超时、下一状态提前到达、重复导致缺目标、超限和无前导状态的 orphan 目标都会输出明确的不完整扫描；已收到目标仍可更新自身轨迹，但不完整扫描绝不据此漏记或删除其他轨迹。

## 交替快照

Linux `/dev/video*` 默认使用原生 V4L2。两个设备会预先打开并分配 mmap buffer，但任意时刻只允许一侧 STREAMON。首次可丢弃 `initial_warmup_frames`，后续切换使用 `switch_warmup_frames`，取到新帧后立即 STREAMOFF。若拍照、推理和关联总耗时超过 `target_switch_interval_s=0.20`，下一侧立即开始，不积压任务，并增加 overrun；0.20 s 只是板端调度目标。

停止时会等待当前捕获/关流超时边界结束；若调度线程仍未退出，不会提前释放它正在使用的 V4L2 资源，并在状态 `errors.scheduler` 中报告。单侧失败进入 `camera_reset_backoff_s`，另一侧仍按自己的可用时间继续。

状态中的 `streamon_ms`、`first_frame_ms`、`capture_ms`、`streamoff_ms`、`inference_ms`、`association_ms` 和 `switch_interval_ms` 都提供 count/p50/p95/max，每侧另有实际 `snapshot_fps`。

## 车型关联

每张图片都重新匹配并整张替换本侧映射：匹配成功使用当前车型，未匹配或 ambiguous 使用 `unknown`，不会继承上一图车型。图片超过 `visual_class_max_age_s` 后全部退回 `unknown`。

候选匹配必须满足水平区间重合：

```text
radar_region = projected_u +/- (projection_half_width_px + image_width * projection_half_width_ratio)
detection_region = bbox_x +/- bbox_width * bbox_expand_ratio
```

代价只使用本图的重合宽度、中心距离、时间差和弱尺寸约束，不使用历史类别、上一帧视觉位置或 class continuity。最优与次优代价差小于 `ambiguity_cost_gap` 时拒绝绑定。

## 风险窗口

每次收到目标的新雷达观测后调用原 `RiskModel`。每个轨迹在固定 0.5 s 窗口内保存所有有效 score，窗口结束取标准中位数：

```text
effective_score = clamp(score_median * warning_sensitivity, 0, 1)
```

再按原 0 到 4 级阈值映射正式 visual/haptic 等级。代表样本是实际分数最接近中位数的真实样本，平局取较新样本。新模式不调用旧 `RiskWarningStabilizer`；旧 stabilizer 仍供纯视觉/legacy 回归。

## HTTP API

若配置了 token，可使用查询参数 `token`、`X-SmartBag-Token` 或 Bearer token。

```sh
curl http://127.0.0.1:8080/api/v1/fusion/status
curl http://127.0.0.1:8080/api/v1/fusion/targets
curl -o left.jpg http://127.0.0.1:8080/api/v1/fusion/left/snapshot.jpg

curl http://127.0.0.1:8080/api/v1/settings/runtime
curl -X PATCH -H 'Content-Type: application/json' \
  -d '{"risk":{"warning_sensitivity":1.2}}' \
  http://127.0.0.1:8080/api/v1/settings/runtime
curl -X POST http://127.0.0.1:8080/api/v1/settings/runtime/reset

curl 'http://127.0.0.1:8080/api/v1/alerts/history?offset=0&limit=20&min_level=3'
curl http://127.0.0.1:8080/api/v1/alerts/EVENT_ID
curl -o alert.jpg http://127.0.0.1:8080/api/v1/alerts/EVENT_ID/image.jpg
```

可在线修改左右安装参数、投影/bbox 区间、时间差、中心距离、最大代价、歧义间隔、灵敏度和各车型权重。未知字段、越界值或持久化失败时整次 PATCH 失败，不会部分应用。

MR20 正式运动量只有水平 `x/z`，没有可靠目标高度。因此 `radar_mount_y_m` 会进入白名单、版本和持久化配置，供垂直标定记录使用，但不会改变当前水平风险或关联；`camera_mount_y_m`、pitch 和名义目标高度只影响调试用垂直投影，垂直坐标不作为严格匹配门限。

三级/四级事件只在 0 到 2 级进入 3/4、3 升 4、或主导轨迹变化时新建；同目标同等级持续存在只更新 `last_seen` 和 `peak_score`，不重复保存图片。图片只取对应侧最新 YOLO 快照，超过 `max_alarm_snapshot_age_s` 会记录 `stale` 而不保存错误旧图。

## 模型状态

本地审计找到 YOLO11n 的 PT、ONNX 和 OM，清单见 `00_admin/local-model-inventory.md/.json`。选定 OM SHA256：

```text
9e3c448ab7309428ea78cfdc509926404220fa74dd56c89e4995366f5f16af95
```

它是 COCO80 检测模型，包含 bicycle、motorcycle、car、truck、bus，输出为 `FP32 [1,84,8400]`。但其静态 AIPP 输入是 `RGB_PLANAR`，当前 `ss928_detection_runner` 硬编码 `NV12/YUV420SP`，因此 **当前不能直接部署**。正式路径统一为 `/root/smartbag/models/vehicle-detector.om`，manifest 和 preflight 会保留 SHA/接口并阻止错误兼容声明。runner 适配、已知图片 PT/ONNX/OM 对齐及 ACL 实板识别仍为 BLOCKED/PENDING。

## 测试

```sh
PYTHONPATH=06_software/board_runtime:06_software/vision_obstacle_tracker \
python3 -m unittest discover -s 06_software/board_runtime/radar_vision_fusion/tests -v

python3 -m unittest 07_tests.integration.test_radar_vision_fusion_pipeline -v
```

离线模拟覆盖单路 STREAMON、200 ms 目标调度、无融合队列、扫描完整性、区间关联、歧义 unknown、逐图替换、500 ms 中位数、参数 API 和告警去重。真实切换时延、OM 识别、雷达完整率、投影误差、多车正确率、CPU/RSS/温度、30 分钟运行、systemd 和独立供电必须实板验证。
