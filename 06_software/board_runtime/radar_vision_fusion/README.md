# 雷达主导的视觉车型融合

本模块实现正式候选架构：MR20 提供全部目标的距离和速度，左右 USB 摄像头交替快照，单个 YOLO 模型只识别车辆类别，目标级绑定后复用 `vision_obstacle_tracker/risk_model.py`。

## 模块

- `radar_tracks.py`：持久雷达轨迹、generation、安装变换和质量指标。
- `alternating_snapshot_classifier.py`：任意时刻只允许一只摄像头 STREAMON，一个 DetectorBackend 共用左右画面。
- `radar_camera_calibration.py`：相机内参/畸变、安装位姿、雷达到相机外参和时间外推投影。
- `radar_vision_association.py`：按侧、时间、FOV 和水平像素门限进行 Hungarian 一对一匹配。
- `visual_binding.py`：确认、缓存、漏检、车型切换和解绑状态机。
- `fusion_runtime.py`：融合目标、共享 RiskModel、逐轨迹 stabilizer、每侧 haptic 聚合和 Controller 事件。
- `fusion_debug_server.py`：只读状态和最新调试快照。
- `fusion_replay.py`：按单调时间轴回放 JSONL。

## 调试 API

默认监听 Controller 配置中的 `fusion.debug_port`：

```sh
curl http://127.0.0.1:8080/api/v1/fusion/status
curl http://127.0.0.1:8080/api/v1/fusion/targets
curl -o left.jpg http://127.0.0.1:8080/api/v1/fusion/left/snapshot.jpg
curl -o right.jpg http://127.0.0.1:8080/api/v1/fusion/right/snapshot.jpg
```

调试 HTTP 不参与风险计算。相机或调试服务失效时，雷达仍以 unknown 类别运行。

## 标定

部署模板是 `/etc/smartbag/fusion-left.json` 和 `fusion-right.json`。模板中的 FOV、位姿和零畸变不是实测值，必须替换。验证命令：

```sh
cd /root/smartbag/radar_vision_fusion
python3 validate_radar_camera_calibration.py /etc/smartbag/fusion-left.json
python3 validate_radar_camera_calibration.py /etc/smartbag/fusion-right.json
```

手工采样工具只记录已知雷达坐标和图像像素，不自动声称求得外参：

```sh
python3 capture_fusion_calibration.py --side left --output /var/lib/smartbag/calibration/fusion-left-observations.jsonl --radar-x -0.5 --radar-z 5.0 --pixel-u 280 --pixel-v 260
```

外参采用 `P_camera = R * P_radar + T`，平移向量不会先与雷达点相加。MR20 没有可靠目标高度，因此水平像素是主要关联约束，垂直像素和 bbox 尺寸只作弱约束。左右安装符号、yaw、平移和相机旋转都必须分别标定，不能只凭“安装高度相近”直接比较雷达 x 与 bbox x。

## 回放

配置 `fusion.record_dir=/var/log/smartbag/fusion` 后会分别记录 scan、classification、detections、association、binding、fused target 和 risk JSONL：

```sh
python3 fusion_replay.py --config /etc/smartbag/config.json --record-dir /var/log/smartbag/fusion
```

## 测试

```sh
PYTHONPATH=06_software/board_runtime:06_software/vision_obstacle_tracker \
python3 -m unittest discover -s 06_software/board_runtime/radar_vision_fusion/tests -v
```

## SS928 OM 状态

`Ss928OmBackend` 已支持持久 native runner：模型只初始化一次，Python 将当前 BGR 快照 letterbox 并转为 NV12，runner 逐请求返回 detections JSON。它不会伪造结果。当前仓库不包含合法车辆 OM；模型输出正确性、板端推理时延和长期稳定性仍需真实 SS928 验收。

native runner 默认必须使用 640x640 输入。`snapshot_classifier.inference_timeout_ms` 默认 5000 ms；单次超时或进程退出会重启 runner 并重试一次，第二次失败后当前侧状态为 `MODEL_ERROR`，下一侧和雷达风险链继续运行。

## 告警与状态

同侧等级变化输出 `alert` 或 `clear`，等级不变的周期保活输出 `heartbeat`。Controller 会用 heartbeat 维持执行器 watchdog，小程序只更新当前状态而不把 heartbeat 重复写入历史。风险事件始终来自逐雷达轨迹稳定后的 `haptic_level`，不会使用 raw risk 或单帧车型分类直接驱动震动。

## 实板验收边界

本机单元测试只能证明状态机、关联、共享 RiskModel 和降级路径。真实 MR20 扫描频率、投影误差、关联成功率、快照频率、OM 正确性、CPU/RSS/温度和 30 分钟稳定性必须在当前接线的 SS928 上测量；缺少设备、合法 OM 或实测标定时应记录 `BLOCKED`，不能用 replay 数值代替。
