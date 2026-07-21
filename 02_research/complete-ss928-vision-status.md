# SS928 完整视觉运行状态

更新时间：2026-07-22

## 基线与代码状态

- 基线分支：`agent/rev2-autonomous-board-runtime`
- 基线 SHA：`c7991cfd62411bb7c99fa4a94b7397769404394a`
- 工作分支：`agent/complete-ss928-vision-runtime`
- 板端 REVISION：未知，当前无法连接板端读取
- 默认板端模型配置：`/root/smartbag/models/yolov8n.om`
- 候选 YOLO11n OM：本地生成但不进 Git，SHA256 为 `9e3c448ab7309428ea78cfdc509926404220fa74dd56c89e4995366f5f16af95`
- NPU adapter：代码已存在，板端安装文件和 SHA256 尚未重新读取
- 运行配置：启动时在 `session.json` 写入脱敏配置及 `configuration_sha256`
- 模型契约：启动时写入 input layout/size/dtype、输入输出字节数和 `1x84x8400 FP32` 输出契约

## 摄像头与标定

- 左摄像头配置：`/dev/v4l/by-path/platform-10320000.xhci_1-usb-0:1.3:1.0-video-index0`
- 右摄像头配置：`/dev/v4l/by-path/platform-10320000.xhci_1-usb-0:1.4:1.0-video-index0`
- 正式运行默认拒绝数字节点、非 `video-index0`、同一真实节点或同一 USB 物理设备。
- 右侧当前配置方向为顺时针 90 度；旋转和翻转在 detector、calibration、overlay 之前统一应用。
- 仓库内左右标定仍是示例/诊断状态，不是现场真实 `calibrated=true` 结果。
- `production` 模式要求左右独立文件、真实相机矩阵、匹配旋转后分辨率、匹配 rotation/flip 和已确认外参，否则拒绝启动。

## 已完成的软件门槛

- 单模型双 UVC 交替采集，任意时刻最多一个 `STREAMON`。
- PC 与 SS928 共用检测后处理后的 `StableTrackIdManager`、`TrackState`、测距测速、Future Conflict Gate、CPA、corridor、moving-away、风险模型和多帧/跨 slice 稳定器。
- SS928 轻量 tracker 保持左右实例隔离，增加真实时间戳、时间型 lost buffer 和中心速度预测；不声称与 BoT-SORT 等价。
- 目标默认类别包含 `person,bicycle,car,motorcycle,bus,truck`。
- session 增加 `detections.csv`、`tracks.csv`、`distance-speed.csv`、`risk-events.csv`、`snapshots/` 和 `overlays/`。
- 新增无 GUI 棋盘采集、内参计算、生产标定校验和黑帧证据工具。
- 新增 `vision_only_validation`，视觉、NPU、跟踪、风险、gateway 和日志开启，TM6605、灯光、音频、雷达、BLE、IMU、GNSS 和 pinmux 写入关闭。

## 当前阻塞

状态：`BOARD_CONNECTION_BLOCKED`

本机以太网已配置 `192.168.1.10/24` 和 `192.168.1.200/24`。历史板端地址 `192.168.1.102` 与 `192.168.1.168` 均无 ping 响应，TCP 22/8080/8081 均不可达；`192.168.1.0/24` 扫描没有发现其他 SSH 主机；当前也没有可识别的 SS928 USB 串口。因此无法读取板端 REVISION、运行摄像头诊断或上传本分支。

### 失败记录

| failure_id | phase | command/check | error | root_cause_hypothesis | repair_attempt | commit | retest_result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `BOARD-CONN-001` | 板端网络发现 | ping 与 TCP 22/8080/8081 检查 `192.168.1.102`、`192.168.1.168` | 两个历史地址均不可达 | 板端未启动、网卡未连接、地址已变化或 PC/板端链路配置不一致 | 保留 PC 的 `192.168.1.10/24` 与 `192.168.1.200/24`，复查两个历史地址并扫描同网段 SSH | 本分支最终 SHA | 仍为 `BOARD_CONNECTION_BLOCKED` |
| `BOARD-CONN-002` | 板端串口发现 | Windows 串口枚举 | 只有蓝牙 COM5/COM6，没有可识别的 SS928 控制台 | 当前 USB 连接未暴露串口，或缺少对应驱动/板端 USB gadget 配置 | 重新枚举串口并排除现有蓝牙端口 | 本分支最终 SHA | 无可用串口，无法绕过网络阻塞 |

失败记录中的 `commit` 将由本分支最终提交 SHA 与 Draft PR 统一追踪；本轮没有通过伪造板端结果关闭失败项。

## 未通过的实板验收

- 两路真实非黑画面和安全的软件恢复流程
- YOLO8 与 YOLO11 的真实目标命中、NPU 时间、RSS、CPU 和温度对比
- 左右真实内参/畸变/安装外参和 `calibrated=true`
- 1/2/3/5 米测距误差
- 静止、接近、远离、横穿速度误差
- Future Conflict、CPA、moving-away、跨 slice 风险实景验证
- 30 分钟连续运行、断线恢复、内存增长检查
- 两次重启、自启动、boot self-test
- 断开电脑后的独立供电启动

当前结论：`VISION_POWER_ONLY_NOT_READY`
