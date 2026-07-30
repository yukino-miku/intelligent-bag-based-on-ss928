# 基于 SS928 的智能背包

本仓库提供 PC 视觉避障原型和 SS928 板端正式运行时。板端主链路由双 MR20 持续提供目标位置与速度，左右 USB 摄像头交替抓取快照，单个 SS928 NPU/OM 模型只补充车辆类别，最终统一进入共享 `RiskModel`、每目标 0.5 秒风险中位数和 Controller。视觉不可用时，雷达轨迹以 `unknown` 类别继续使用同一风险核心，不退回旧阈值算法。

> 这是工程原型，不是经过安全认证的防碰撞设备。真实使用前必须完成硬件标定、误报/漏报、端到端时延、热稳定、断电恢复和独立供电测试。

## 一键部署

在 SS928 Ubuntu 板端执行：

```sh
git clone https://github.com/yukino-miku/intelligent-bag-based-on-ss928.git
cd intelligent-bag-based-on-ss928
sudo ./install-on-ss928.sh --interactive
sudo reboot
```

交互安装会校验 AArch64 runner 和正式 OM、生成 API Token、发现并确认左右摄像头、安装 systemd，并引导融合标定。标定未完成时会保持安全的 `radar_only`；该模式仍走共享 RiskModel 和 0.5 秒窗口。完成标定后重新运行 `sudo ./install-on-ss928.sh --full`。

```sh
systemctl status smartbag.target
journalctl -u smartbag-alert.service -f
sudo ./validate-on-ss928.sh --full --duration 30m
```

详细步骤见 [板端部署说明](09_deliverables/board_deploy/README.md)。

## 板端数据链

```text
双 MR20 UDP -> 完整扫描 -> RadarTrackManager -> 共享 RiskModel
                                             ^
左右 UVC 交替快照 -> vehicle-detector.om -> 当前帧一一关联

共享 RiskModel -> 每目标 0.5 秒中位数/质量门 -> Controller
               -> TM6605/LRA + 灯 + 可选音频 + BLE + L3/L4 本地事件
```

- `radar_primary_visual_classification`：正式 full 模式，雷达决定运动量，视觉只补充 `bicycle/motorcycle/car/truck/bus` 类别。
- `radar_only`：视觉关闭，类别为 `unknown`、权重为 1.0，风险算法完全相同。
- `legacy_mr20_threshold_test`：仅显式诊断旧硬件，不进入默认安装或 systemd。
- `legacy_dual_vision`：保留 PC 视频回归，不是板端正式主链。

风险输出区分 raw、visual、haptic 和实际执行器等级。正式震动只使用稳定后的 haptic 结果；L3/L4 快照按相同 `frame_id + detection_id` 绘制，原帧过期时不把旧框套到新图。

## 正式交付资产

| 内容 | 路径 | SHA256/状态 |
|---|---|---|
| SS928 车辆 OM | `09_deliverables/board_deploy/models/vehicle-detector.om` | `9e3c448ab7309428ea78cfdc509926404220fa74dd56c89e4995366f5f16af95` |
| AArch64 runner | `09_deliverables/board_deploy/bin/aarch64/ss928_detection_runner` | `332c792dc7a64190e182f6260edb455668e1885e883a0e48c794728eed024737` |
| OM inspector | `09_deliverables/board_deploy/bin/aarch64/om_inspect` | manifest 校验 |
| 模型/runner 契约 | 同目录两个 manifest | 静态契约 PASS，板端 ACL 检测 PENDING |

模型是 YOLO11n COCO80 的 SS928 转换产物，输入为 FP32 RGB_PLANAR `[1,3,640,640]`，输出为 FP32 `[1,84,8400]`。runner 根据 ACL descriptor 选择 NV12、RGB UINT8 或 RGB FP32 预处理并拒绝不匹配形状。`runner_compatible=true` 只表示静态契约匹配，不能替代真实板端检测证据。

仓库按 AGPL-3.0-only 分发；模型、生成音频和第三方来源分别见 [MODEL_LICENSES](MODEL_LICENSES.md)、[AUDIO_LICENSES](AUDIO_LICENSES.md) 和 [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md)。厂商 SDK、ACL runtime、系统镜像、工具链、密钥和个人测试视频不进入 Git 或 Release。

## PC 视觉回归

```powershell
cd .\06_software\vision_obstacle_tracker
py -m pip install -r requirements.txt

# USB 摄像头
py vision_obstacle_tracker.py --source camera --runtime-profile cpu_demo --profile

# 视频检测
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --profile

# 保存完整带框录像
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --save-output D:\path\overlay.mp4 --no-display
```

`--display-every-n` 只降低窗口刷新频率，不跳过 YOLO、跟踪、测距和风险计算；`--max-frames` 限制实际处理帧数。视觉风险语义和参数见 [视觉 README](06_software/vision_obstacle_tracker/README.md)。

## 目录入口

| 内容 | 文档 |
|---|---|
| 板端安装、相机、MR20、API、标定与排障 | [board_deploy](09_deliverables/board_deploy/README.md) |
| 系统进程与事件协议 | [03_design](03_design/board-process-architecture.md) |
| 40Pin 唯一接线事实源 | [40pin-usage](04_hardware/ss928/40pin-usage.md) |
| 微信小程序导入与本地/CloudBase 部署 | [小程序 DEPLOYMENT](06_software/mobile/ssminiprogram/DEPLOYMENT.md) |
| 分支收敛与归档 tag | [final branch plan](00_admin/final-branch-consolidation-plan.md) |
| 本地资产审计与 clone 就绪度 | [asset inventory](00_admin/local-deployment-asset-inventory.md)、[clone readiness](00_admin/clone-install-readiness.md) |
| RC2 离线包 | [releases](09_deliverables/releases/README.md) |

## 验证状态

- `CLONE_INSTALL_READY=true` 仅在 GitHub 远程干净 clone、资产校验、full/radar-only mock 安装、重复安装、卸载保留数据和 RC2 包检查全部通过后成立。
- `BOARD_INSTALL_VERIFIED=false`：本次发布没有把历史板端记录冒充当前 RC2 完整安装结果。
- `POWER_ONLY_AUTOSTART_READY=false`：尚无 RC2 reboot 后拔除电脑、独立供电冷启动证据。
- 真机验收统一执行 `sudo ./validate-on-ss928.sh --full --duration 30m`，并另做 reboot 与独立供电测试。
