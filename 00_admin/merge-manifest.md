# SS928 板端整合清单

整合日期：2026-07-15。只读来源：`sanda-tt/ss928`，ref `codex/dx-gp21-tracker`，提交 `d7e10fd06dc553f94d2db3a3d19987ec8648f7dc`。目标分支：`agent/ss928-board-integration`。未使用 unrelated histories 合并，未修改来源仓库。

| 原路径 | 主要功能 | 运行方式 | 硬件依赖 | 依赖 | 迁移 | 目标路径 | 重构 | 重复/替代 | 决定与理由 |
|---|---|---|---|---|---|---|---|---|---|
| `work/imx347_mipi_preview` | IMX347 MPP 预览 | make/板端二进制 | sensor0、MIPI、I2C7 | C、MPP | 是 | `05_firmware/ss928/board_samples/...` | 是 | 无 | 只迁源码/Makefile/README，删除二进制和 `.o`，SDK 根改为变量 |
| `work/bmi270_i2c_pose` | BMI270 I2C C 诊断 | make/CLI | I2C0 | C、Bosch header | 有限 | `05_firmware/ss928/diagnostics/...` | 是 | 被 Python 正式服务覆盖 | 仅保留诊断价值，不作为服务，不复制二进制 |
| `work/linux_bmi270_backpack` | 姿态、趋势、IIO/I2C、BLE | Python/systemd | BMI270 | Python、BlueZ/dbus | 是 | `06_software/board_runtime/bmi270_backpack` | 是 | 正式 BMI 模块 | 默认 no-BLE，直接接 fall bridge；不复制 config blob/原始 CSV |
| `work/imu_fall_detector` | 跌倒/撞击状态机 | Python/模拟 | BMI270 数据 | Python | 是 | `06_software/board_runtime/imu_fall_detector` | 是 | 独立事件类型 | 保留测试，BMI 样本直接转 `ImuSample` |
| `work/dx_gp21_tracker` | NMEA、WGS84、轨迹、BLE 命令 | Python/UART | UART4、GNSS | Python、BlueZ/dbus | 是 | `06_software/board_runtime/dx_gp21_tracker` | 是 | 无 | 默认 no-BLE，增加统一命令 stdin |
| `work/smartbag_alert_controller` | JSONL、PWM、音频、BLE | Python | 四路 PWM/I2S/BLE | Python、BlueZ/dbus | 是 | `06_software/board_runtime/smartbag_alert_controller` | 是 | 板端主控制器 | 加入单/双摄、超时、过期拒绝、退出清振和统一 BLE 路由 |
| `work/smartbag_alert_audio_build` | L/R 1..4 音频中间产物 | ffmpeg/工具 | 无 | PCM/AAC | 否 | `06_software/tools/audio_prepare` | 是 | 与 deploy 重复 | 只保留生成工具；音频来源许可不清，不复制 PCM/AAC |
| `work/smartbag_alert_audio_deploy` | 部署 AAC | sample_audio | MAX98357 | AAC、厂商 sample | 否 | 部署文档/空 assets 约定 | 是 | 与 build 重复 | 不复制来源音频；默认关闭，部署者提供合法素材 |
| `work/max98357_i2s_test` | 单路 I2S 播放测试 | sample_audio | MAX98357 | PCM/AAC | 否 | 硬件文档 | 否 | 被统一音频路径替代 | 重复音频且来源不明，只迁接线知识 |
| `work/mt5710_voice_call` | 5G 语音呼叫辅助 | Python CLI | MT5710 | Python/厂商接口 | 可选 | `06_software/optional/mt5710_voice_call` | 是 | 非主链 | 保留源码，不进入默认启动 |
| `work/ssminiprogram` | GNSS/BMI/告警小程序 | 微信开发者工具 | 手机 BLE | 原生小程序 JS | 是 | `06_software/mobile/ssminiprogram` | 是 | 无 | 清除 cloud/example/placeholder/未引用资源，统一设备名和命令 |
| `work/ld2417-radar-web` | 雷达 Web 调试 | Node/Python | LD2417 雷达 | JS/Python | 否 | 无 | 否 | 与纯视觉路线冲突 | 当前不采用雷达决策 |
| `work/radar_uart_test` | 雷达 UART dump | make/CLI | 雷达 UART | C | 否 | 无 | 否 | 与纯视觉路线冲突 | 当前不采用雷达决策 |
| `skills/ss928-direct-board-debug` | SSH/SFTP 调试工具包装 | Python | 网络/SSH | paramiko | 提取 | `06_software/tools/board_debug` | 是 | skill 元数据无运行价值 | 只迁脚本，去除固定密码/IP和 skill metadata |
| `skills/ss928-max98357-audio-playback` | 音频准备工具包装 | Python/ffmpeg | 无 | Python、ffmpeg | 提取 | `06_software/tools/audio_prepare` | 是 | 与 audio build 重叠 | 只迁生成工具和普通 README |
| `skills/ss928-mt5710-5g-validation` | MT5710 验证说明 | 人工流程 | MT5710 | 厂商工具 | 否 | 可选模块 README | 是 | skill 包装 | 不迁 metadata，只保留可执行脚本 |
| `skills/miniprogram-development` | 小程序通用说明 | 文档 | 无 | 小程序工具 | 否 | 无 | 否 | 通用 skill | 不属于产品运行时 |
| `skills/wechat-miniprogram-native` | 小程序 skill | 文档 | 无 | 小程序工具 | 否 | 无 | 否 | 通用 skill | 不属于产品运行时 |
| `agent.md` | 代理操作说明 | 无 | 无 | 无 | 否 | 无 | 否 | 非产品文件 | 不迁移 |
| `40pin_usage.md` | 来源引脚汇总 | 文档 | 40Pin | 无 | 整理 | `04_hardware/ss928/40pin-usage.md` | 是 | 多模块接线重复 | 合并为唯一事实来源并检查冲突 |

## 目标仓库审计

| 目标路径 | 审计结果 | 决定 |
|---|---|---|
| `06_software/vision_obstacle_tracker` | 已有 YOLO/BoT-SORT、测距、Future Conflict、stabilizer、visual/haptic、自身前景、CSV 和性能参数 | 保留主流程，只增加 backend 接口、board profile 和稳定 haptic JSONL |
| `06_software/usb_camera_recorder` | PC 摄像头采集工具，视觉测试仍使用 | 保留 |
| `06_software/radar_visualizer` | 活动雷达实验，与当前纯视觉路线不符 | 删除并记录，历史由 Git 保存 |
| 根 README/CHANGELOG/project-log | 有完整视觉历史，但根 README 过长，仍含旧雷达路线 | 根 README 改为入口；日志保留历史并追加路线变更 |
| requirements/design/hardware/tests | 原有大多为文档或零散测试，缺板端统一协议与部署描述 | 新增板端需求、设计、硬件、部署和集成测试，不删除仍有价值文档 |
