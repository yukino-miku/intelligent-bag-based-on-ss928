# 基于 SS928 的智能背包

本仓库是项目唯一正式代码库，覆盖 PC 视觉原型、SS928 板端运行时、硬件接线、统一告警 Controller、CloudBase 与微信小程序。新的板端正式候选架构以双 MR20 的位置/速度作为风险运动数据源，左右 USB 摄像头只交替快照识别车型；融合后复用原视觉 RiskModel。PC 纯视觉模式继续保留用于回归和视频调试。

## 系统能力

- **视觉避障**：USB camera/视频输入、Ultralytics YOLO、BoT-SORT、单目测距/测速、CPA、有限前方走廊、Future Conflict Gate、多帧稳定、visual/haptic 分层、自身前景/边缘截断保护、risk CSV、overlay 与保存视频。
- **雷达主导融合**：双 MR20 按 0x60A/0x60B 完整性组包；完整和不完整扫描明确区分，不完整扫描不会误删未上报轨迹。
- **交替快照分类**：Linux 原生 V4L2 预开两路 fd/mmap，左右任意时刻最多一路 STREAMON，共用一个 YOLO/OM；0.20 秒是相邻侧启动调度目标，不是未经实板验证的承诺。
- **当前图关联**：雷达投影容差区间与扩展 bbox 必须水平重合，再用 Hungarian 一一匹配；每张图原子替换本侧车型映射，未匹配、歧义或过期均为 unknown，不做历史车型绑定。
- **目标级风险**：融合内部没有雷达/视觉混合队列。每次新雷达观测调用原 RiskModel，每个轨迹用固定 0.5 秒 score 中位数和可调灵敏度输出正式等级。
- **告警输出**：Controller 按侧选择中位数窗口中最危险目标，驱动 TCA9548A 后的左右 TM6605/LRA、Pin7/Pin32 灯和可选 MAX98357 音频；legacy 视觉才继续使用旧多帧 stabilizer。
- **姿态与跌倒**：BMI270 单进程采集，支持 IIO/用户态 I2C、姿态、驼背累计提醒、跌倒/撞击融合；最终严重跌倒可异步上云并按配置发送短信或电话。
- **定位与通信**：DX-GP21 NMEA/WGS84/JSONL 轨迹可选；MT5710 正式服务只管理 5G NCM；GNSS 无效时不会伪造位置。
- **云和移动端**：CloudBase telemetry/查询函数，统一 `SS928-SmartBag` BLE NUS，以及双摄、交通危险事件、运行参数、轨迹、姿态和远程命令页面。三级/四级事件按 event_id 去重并可保存同侧图片。
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
| 雷达主导融合设计与边界 | [设计审计](02_research/radar-primary-vision-fusion-design.md)、[模块 README](06_software/board_runtime/radar_vision_fusion/README.md) |
| 本地 PT/ONNX/OM 审计与部署阻塞 | [模型清单](00_admin/local-model-inventory.md)、[部署 manifest](09_deliverables/board_deploy/models/vehicle-detector.manifest.json) |
| 克隆安装就绪度与本机资产 | [readiness](00_admin/clone-install-readiness.md)、[资产清单](00_admin/local-deployment-asset-inventory.md) |
| 微信小程序导入与 CloudBase | [小程序部署](06_software/mobile/ssminiprogram/DEPLOYMENT.md) |
| 第三方来源和许可边界 | [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md) |
| 仓库根许可状态 | [LICENSE_STATUS](LICENSE_STATUS.md) |

## PC 快速运行

```powershell
cd .\06_software\vision_obstacle_tracker
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
git clone --branch agent/radar-primary-vision-class-fusion --single-branch \
  https://github.com/yukino-miku/intelligent-bag-based-on-ss928.git
cd intelligent-bag-based-on-ss928

# 当前可审计的安全降级安装；不启用未验收的视觉分类
sudo ./install-on-ss928.sh --radar-only --yes

# 完整模式只有在正式模型 manifest、实板 descriptor 和标定全部通过后才允许
# sudo ./install-on-ss928.sh --model-source /合法来源/vehicle-detector.om --yes
```

默认示例 profile 是 `radar_primary_visual_classification`：双 MR20 + 单模型交替快照 + BMI270 + TM6605/LRA + 灯。Controller 是 BLE、振动、灯、音频、雷达 worker 和融合运行时的唯一所有者；GNSS/BMI 默认 `--no-ble`。摄像头或 YOLO 失败不会清空雷达轨迹，只会让车型退化为 unknown；服务停止、空风险窗口、事件过期和异常仍由 clear/safe-off 清除输出。

## NPU/OM 当前状态

本地完整审计找到 YOLO11n 的 `.pt`、`.onnx` 和已由 ATC 生成的 `.om`，详见 [模型清单](00_admin/local-model-inventory.md)。候选 OM SHA256 为 `9e3c448ab7309428ea78cfdc509926404220fa74dd56c89e4995366f5f16af95`。当前 AArch64 runner 已根据 ACL descriptor 支持 NV12 UINT8、RGB_PLANAR UINT8 和 RGB_PLANAR FP32，并由 Python 统一传 BGR24 帧；PT/ONNX 三帧同图车辆结果已通过。但候选 OM 的真实板端 descriptor、检测结果和 Ultralytics AGPL/仓库根许可兼容性仍未通过，因此模型不进 Git，`runner_compatible=false`。正式文件名统一为 `/root/smartbag/models/vehicle-detector.om`，manifest/preflight 会阻止错误兼容声明；OpenVINO 只代表 CPU 优化，不等于 SS928 NPU。

## 已验证与限制

- Windows 本地已通过 385 项 Python、12 个小程序/CloudBase Node 测试文件、4 个 NPU native C++ tests、1 个 C 兼容核心测试和 1 个 C++ backend 测试，并完成 compileall、38 个 JavaScript、42 个 JSON、30 个 Shell、凭据扫描和 `git diff --check`；命令口径和限制见 [integration-status](00_admin/integration-status.md)。
- 既有实板记录确认 SS928 Ubuntu/aarch64、两台 UVC 枚举和单路出帧；当时两相机共用 USB 2.0 hub，双路出现 `ENOSPC`。更换端口后的持续双路采集、正式 detector FPS/内存/温度仍须复测。
- 本分支 2026-07-28 收尾时电脑物理以太网接口断开，板端私网地址不可达，因此没有执行上传、服务启动或 reboot 验证。
- TM6605、灯、MR20、BMI270、DX-GP21、MAX98357、MT5710、WS73、Tsensor 和 reboot 自启都必须以当前实际接线再验收，文档中的历史结果不能替代本轮实板测试。
- 单目避障与跌倒判断不是安全认证系统；真实使用前必须做标定、硬件在环、误报/漏报、端到端时延、热稳定和断电恢复测试。
- 模型、SDK、真实标定、设备密码/IP、Cloud token、手机号、`08_media` 和大体积来源归档不提交 Git。
