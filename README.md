# 基于 SS928 的智能背包

本仓库是项目唯一正式代码库，覆盖 PC 视觉原型、SS928 板端运行时、硬件接线、统一告警 Controller、CloudBase 与微信小程序。正式避障风险仍由纯视觉模型计算；MR20 已作为可选、默认关闭的独立告警来源接入 Controller，不参与或改写视觉 Future Conflict Gate。

## 系统能力

- **视觉避障**：USB camera/视频输入、Ultralytics YOLO、BoT-SORT、单目测距/测速、CPA、有限前方走廊、Future Conflict Gate、多帧稳定、visual/haptic 分层、自身前景/边缘截断保护、risk CSV、overlay 与保存视频。
- **固定双摄**：正式板端采用左右两个固定 USB detector，各自独占 camera、tracker、风险状态和 latest frame；不使用交替采集作为正式方案。
- **告警输出**：Controller 按 `(source, side)` 融合稳定视觉事件和可选 MR20，驱动 TCA9548A 后的左右 TM6605/LRA、Pin7/Pin32 灯和可选 MAX98357 音频。
- **姿态与跌倒**：BMI270 单进程采集，支持 IIO/用户态 I2C、姿态、驼背累计提醒、跌倒/撞击融合；最终严重跌倒可异步上云并按配置发送短信或电话。
- **定位与通信**：DX-GP21 NMEA/WGS84/JSONL 轨迹可选；MT5710 正式服务只管理 5G NCM；GNSS 无效时不会伪造位置。
- **云和移动端**：CloudBase telemetry/查询函数，统一 `SS928-SmartBag` BLE NUS，以及双摄画面、告警、轨迹、姿态、远程命令页面。
- **板端运维**：统一 `/root/smartbag`、`/etc/smartbag`、`/var/lib/smartbag`、`/var/log/smartbag`，支持 install/upgrade/preflight/safe-off/status/logs/systemd target 和硬件 profile。

## 关键文档

| 内容 | 入口 |
|---|---|
| PC 视觉运行、参数与风险语义 | [视觉 README](06_software/vision_obstacle_tracker/README.md) |
| SS928 安装、配置、自启和排障 | [部署 README](09_deliverables/board_deploy/README.md) |
| 整合后的进程和硬件所有权 | [系统架构](03_design/integrated-system-architecture.md) |
| 40Pin 唯一接线事实源 | [40Pin 表](04_hardware/ss928/40pin-usage.md) |
| 来源逐文件审计 | [整合计划](00_admin/sanda-full-integration-plan.md)、[24,421 文件 manifest](00_admin/sanda-full-file-manifest.csv) |
| 当前完成/未验证项 | [integration-status](00_admin/integration-status.md) |
| 第三方来源和许可边界 | [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md) |

## PC 快速运行

```powershell
cd D:\mywork\code\embedded-contest-project\06_software\vision_obstacle_tracker
py -m pip install -r requirements.txt

# 摄像头实时检测
py vision_obstacle_tracker.py --source camera --runtime-profile cpu_demo --profile

# 视频检测
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --profile

# 保存完整带框视频
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --save-output D:\path\overlay.mp4 --no-display
```

`--display-every-n` 只降低窗口刷新频率，不减少 YOLO、跟踪、测距或风险计算；`--max-frames` 限制实际处理帧数。详细参数以视觉 README 和 `--help` 为准。

## SS928 快速部署

```sh
cd /path/to/repo/09_deliverables/board_deploy
sudo sh install.sh /path/to/repo
sudo install -m 0644 /合法来源/yolo11n.pt /root/smartbag/models/yolo11n.pt
sudoedit /etc/smartbag/config.json
sudoedit /etc/smartbag/calibration-left.json
sudoedit /etc/smartbag/calibration-right.json
sudo sh check-runtime-deps.sh
sudo sh preflight.sh /etc/smartbag/config.json
sudo systemctl enable --now smartbag.target
sh status.sh
sh logs.sh -f
```

默认 profile 是固定左右 USB 双摄 + BMI270 + TM6605/LRA + 灯，MR20、GNSS、音频和 MT5710 依硬件状态配置。Controller 是 BLE、振动、灯、音频和雷达 worker 的唯一所有者；GNSS/BMI 默认 `--no-ble`。任何 detector 退出、事件过期、服务停止或异常都会清除对应输出，`safe-off` 在退出后再次兜底。

## NPU/OM 当前状态

`06_software/vision_obstacle_tracker/ss928_backend` 已迁移 ACL 模型合约、NV12 letterbox、YOLO 解码/NMS、离线 runner 和 detections JSONL 协议。来源实板证据显示固定输入 ACL 100 帧可运行，但工厂 OM 未输出可信目标；双 USB 实时帧、NPU 检测、BoT-SORT/风险和 overlay 的完整链尚未验收。当前正式实时后端仍是 Python Ultralytics 路径；OpenVINO 只代表 CPU 优化，不能写成 SS928 NPU。

## 已验证与限制

- Windows 本地已通过 290 项 Python、11 个小程序/CloudBase Node 测试文件和 4 个 NPU native C++ tests，并完成 Python/JS/JSON/Shell/import/manifest 静态检查；命令口径和限制见 [integration-status](00_admin/integration-status.md)。
- 既有实板记录确认 SS928 Ubuntu/aarch64、两台 UVC 枚举和单路出帧；当时两相机共用 USB 2.0 hub，双路出现 `ENOSPC`。更换端口后的持续双路采集、正式 detector FPS/内存/温度仍须复测。
- 本分支收尾时电脑物理以太网为断开状态、板端 SSH 不可达，因此没有执行上传、服务启动或 reboot 验证。
- TM6605、灯、MR20、BMI270、DX-GP21、MAX98357、MT5710、WS73、Tsensor 和 reboot 自启都必须以当前实际接线再验收，文档中的历史结果不能替代本轮实板测试。
- 单目避障与跌倒判断不是安全认证系统；真实使用前必须做标定、硬件在环、误报/漏报、端到端时延、热稳定和断电恢复测试。
- 模型、SDK、真实标定、设备密码/IP、Cloud token、手机号、`08_media` 和大体积来源归档不提交 Git。
