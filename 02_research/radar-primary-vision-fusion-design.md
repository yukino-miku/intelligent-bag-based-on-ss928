# 雷达主导与视觉车型融合设计

## 1. 审计结论

本轮基线为 `agent/full-sanda-integration@c3ef9c012543cdc02c708449572e8645b98dcf48`。旧实现中，MR20 与视觉是两个只在 Controller 中按 `source+side` 取高等级的独立告警源，没有目标级关联：

- `mr20_radar.py` 用 `0x60A` 表示一轮目标数和 `measurement_count`，用随后的多个 `0x60B` 表示目标。
- 旧 `MR20RadarWorker._flush()` 将一轮目标交给简单 TTC evaluator，只发出一个最高目标，其他目标在告警边界前丢失。
- 视觉进程独立运行 YOLO、BoT-SORT、单目测距测速、RiskModel 和 stabilizer，再按 side 输出 `vision_alert`。
- Controller 只能合并每侧等级，无法知道雷达目标与视觉车型是否属于同一辆车。

## 2. MR20 帧和坐标

MR20 UDP 帧固定 14 字节，头尾为 `AA AA`/`55 55`。CAN ID 在封装中使用小端字节：

- `0x60A`：`target_count`、16-bit `measurement_count`。
- `0x60B`：`target_id`、纵向/横向距离、纵向/横向速度和 stopped/oncoming/going/crossing 状态。

解析公式保持来源实现，不在 parser 层改变符号。融合层统一背包坐标：`x` 向右为正，`z` 向背包正后方为正。每只雷达先应用独立的 `invert_*`，再应用 `mount_x_m`、`mount_z_m`、`mount_yaw_deg`。左右安装不能共用未经验证的符号假设。

## 3. 旧雷达风险算法

旧 `RadarRiskEvaluator` 只使用纵向距离、配置化接近速度符号和四组 TTC/距离/最低速度阈值，并要求目标连续出现若干帧。它不计算横向路径冲突、CPA、Future Conflict、车型严重性或视觉/震动分层。该 evaluator 仅保留为 `radar_only`/兼容接口，新正式模式不使用其输出。

## 4. 现有 RiskModel 输入和类别规则

共享 RiskModel 需要目标 ID、类别、`x/z/vx/vz`、距离、速度、轨迹年龄、距离/速度/观测质量、位置抖动、距离趋势、接近一致性、路径冲突一致性和质量 flags。核心算法继续包括：

- radial closing speed、有限轨迹最小距离、TTC 和 DRAC；
- CPA 和 Future Conflict；
- personal space、warning corridor、moving-away 和 contextual cap；
- large_vehicle/small_rider/unknown severity profile；
- visual/haptic 分层和逐目标 RiskWarningStabilizer。

车型 multiplier 只在 RiskModel 内乘一次：bicycle `0.92`、motorcycle `0.96`、car `1.00`、truck/bus `1.10`、unknown `1.00`。融合层不能再次乘权重。

## 5. 新正式数据流

```text
双 MR20 持续在线
  -> 完整 RadarScan
  -> RadarTrackManager (radar_name:target_id:generation)
  -> 时间外推 + 雷达到相机投影
  -> 单模型左右交替快照 YOLO
  -> 一侧一对一全局匹配
  -> VisualClassBindingManager
  -> FusedRadarTarget
  -> 原 RiskModel
  -> 每条雷达轨迹独立 stabilizer
  -> 每侧最高稳定 haptic_level
  -> Controller/震动/灯/音频/BLE
```

雷达始终提供距离和速度。相机只提供车辆类别；不运行 BoT-SORT、视觉测距测速、视觉 CPA、光流或 `vision_alert`。摄像头、YOLO 或绑定失败时，雷达继续使用 `unknown` 类别完整计算风险。

## 6. 雷达轨迹生命周期

每个活动轨迹键为 `radar_name:target_id:generation`。同一 ID 在超时或连续缺失后再次出现时 generation 增加，不继承车型、绑定或 stabilizer 状态。轨迹保留有界位置/速度历史，并计算雷达质量、位置跳变、距离趋势、接近一致性和路径冲突一致性。左右雷达及其 ID 空间完全独立。

## 7. 快照、同步和关联

交替分类器只有一个进程和一个 DetectorBackend。每次只打开一只 UVC，丢弃预热帧、取得最新图、立即关闭，再做 YOLO；不保留旧帧队列。建议使用固定物理 USB 口的 `/dev/v4l/by-path`。

分类帧和雷达扫描都使用 `time.monotonic()`。关联在轨迹有界历史中选择最接近拍照时间的状态，并按速度外推。超过 `association_max_time_delta_s` 的状态不得匹配。

MR20 没有可靠目标高度，因此水平投影是硬条件，垂直投影只用于调试。候选代价由水平投影、时间差、历史车型、运动连续性和弱 bbox 尺寸项组成，再用 Hungarian 全局最小代价完成一对一分配。跨侧、超 FOV、超时或超误差目标保持 unknown。

## 8. 持久车型绑定

绑定键是雷达 `track_key`，不是临时 detection ID。默认同类连续匹配两次才 BOUND；一次漏检或切换期间保持 cached binding；连续漏检、超时、离开 FOV、雷达轨迹删除或 generation 改变才清除。车型切换默认需要三次确认，历史绑定不能突破几何硬门限。

## 9. 保留和禁用范围

继续保留：PC 纯视觉完整模式、旧 `legacy_dual_vision` 回归模式、`radar_only`、原 RiskModel、原车型权重、多帧升级确认、降级迟滞、紧急 fast path、Controller 安全清振、BLE/小程序兼容字段。

新正式模式禁用：两个完整视觉风险进程、视觉测距测速、BoT-SORT、视觉风险事件、旧简单 MR20 evaluator 告警，以及旧双 detector HTTP gateway 的默认自启动。

## 10. 当前验证边界

Windows 模拟测试已验证完整扫描、多目标轨迹、ID generation、安装变换、单模型交替状态、一对一匹配、绑定确认/漏检、共享 RiskModel 和 unknown 降级。以下不能由本地模拟结果替代：

- 左右 MR20 的真实符号、安装位姿、扫描频率和多车 ID 行为；
- 两份相机内参/畸变、雷达到相机外参和像素投影误差；
- 合法车辆 OM 的真实类别输出和准确率；
- 单 UVC STREAMON 交替时延、每侧快照频率、NPU 延迟、CPU/RSS/温度；
- 30 分钟运行、systemd、自启动和拔掉电脑后的独立运行。

没有以上实测记录前，状态必须写为 `BLOCKED` 或“待硬件验证”，不能宣称正式后端验收完成。
