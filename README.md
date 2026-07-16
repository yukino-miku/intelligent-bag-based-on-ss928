# 基于 SS928 的智能背包

本项目当前采用纯视觉避障：检测、跟踪、单目距离/速度、Future Conflict Gate、多帧稳定、visual/haptic 分层和自身前景过滤均由 `06_software/vision_obstacle_tracker` 完成。毫米波雷达不参与当前风险判断，旧雷达活动目录已移除。

## 当前能力

- PC：USB 摄像头或视频输入，Ultralytics YOLO + BoT-SORT，ROI/OpenVINO CPU/profile，overlay、风险 CSV 和带框视频保存。
- SS928：双 USB 摄像头固定左右 detector、`board_dual_balanced`/`board_cpu`、容量 1 最新帧、稳定 haptic JSONL、左右独立四路 PWM、双路 LAN snapshot/MJPEG、可选 MAX98357 音频。
- 传感器：DX-GP21 GNSS/NMEA/轨迹；BMI270 IIO/I2C、姿态和短时运动趋势；独立跌倒/撞击事件。
- 移动端：统一 `SS928-SmartBag` BLE NUS 传告警/GNSS/IMU/系统状态；原生微信小程序显示左右画面、自动告警历史、轨迹和姿态。视频不走 BLE。

## 快速入口

| 内容 | 文档/目录 |
|---|---|
| PC 视觉运行与调参 | [vision_obstacle_tracker](06_software/vision_obstacle_tracker/README.md) |
| 板端部署 | [board_deploy](09_deliverables/board_deploy/README.md) |
| 双 USB 板端资料审计 | [dual-usb-camera-board-analysis.md](02_research/dual-usb-camera-board-analysis.md) |
| 板端架构 | [board-process-architecture.md](03_design/board-process-architecture.md) |
| 事件与 BLE 协议 | [event-protocol.md](03_design/event-protocol.md)、[ble-protocol.md](03_design/ble-protocol.md) |
| 40Pin 唯一接线表 | [40pin-usage.md](04_hardware/ss928/40pin-usage.md) |
| 来源审计与迁移决定 | [merge-manifest.md](00_admin/merge-manifest.md) |
| 来源功能清单 | [ss928-source-inventory.md](02_research/ss928-source-inventory.md) |
| 清理与当前状态 | [cleanup-report.md](00_admin/cleanup-report.md)、[integration-status.md](00_admin/integration-status.md) |

## PC 视觉示例

```powershell
cd D:\mywork\code\embedded-contest-project\06_software\vision_obstacle_tracker
py -m pip install -r requirements.txt
py vision_obstacle_tracker.py --source camera --runtime-profile cpu_demo --profile
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --profile
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --save-output D:\path\overlay.mp4 --no-display
```

## SS928 快速部署

```sh
cd 09_deliverables/board_deploy
sudo sh install.sh /path/to/intelligent-bag-based-on-ss928
sudo install -m 0644 /path/to/yolo11n.pt /root/smartbag/models/yolo11n.pt
# 编辑 /etc/smartbag/config.json 和左右两份 calibration，再检查
sudo sh preflight.sh /etc/smartbag/config.json
sudo sh start-all.sh
sh logs.sh -f
```

默认启动左右两个固定 detector 和双路视频 gateway。先在 `/etc/smartbag/config.json` 配置两个不同的稳定设备路径、两份独立标定和左右 PWM，再运行 preflight；相同型号/序列号摄像头应固定物理口并使用 by-path，不能依赖冲突的 by-id。GNSS 与 BMI270 默认 `--no-ble`，由 controller 独占 BLE。震动只使用稳定后的 `haptic_risk_level`；单侧 detector 退出只清本侧，事件过期、异常或服务停止也会清振。

## 未完成与安全边界

- `Ss928OmBackend` 尚无与当前 Python tracker/风险链兼容的真实 MPP/SVP/NPU API，只定义接口；归档中的 `.om` C/C++ sample 和 OpenVINO CPU 都不能冒充已完成后端。
- 2026-07-16 实板确认两台 UVC 相机能分别出帧，但当前二者共用同一 USB 2.0 hub，双路启动出现 `ENOSPC`；板上仅约 952 MiB 内存且缺少视觉依赖。换到不同根控制器、补齐 aarch64 依赖并完成长期测试前，不声明板端双路“实时可用”。
- 模型、厂商 SDK、MPP、BMI270 config blob、设备密码/IP 不进入仓库。
- 单目测距和风险提示不是安全认证系统；真实使用前必须做相机标定、硬件在环、误报/漏报、时延、温度和断电恢复测试。
- 40Pin、PWM、电机供电、I2S 和传感器电平必须按硬件文档核验，不能直接用 GPIO 给电机或功放供电。

`08_media/` 和 `10_archive/` 仅本地使用，不上传 GitHub。
