# 部署内容清单

| 源目录 | 板端目录 | 默认启动方式 |
|---|---|---|
| `06_software/vision_obstacle_tracker` | `/root/smartbag/vision` | controller 监督一个模型和左右 UVC 交替采集 |
| `board_runtime/smartbag_alert_controller` | `/root/smartbag/controller` | `smartbag-controller.service`，统一执行器/BLE/GNSS/IMU/MR20 |
| `board_runtime/common` | `/root/smartbag/common` | controller 资源采样与公共协议 |
| `board_runtime/dx_gp21_tracker` | `/root/smartbag/gnss` | controller 子进程，默认 no-BLE |
| `board_runtime/bmi270_backpack` | `/root/smartbag/imu` | controller 子进程，默认 no-BLE |
| `board_runtime/imu_fall_detector` | `/root/smartbag/imu_fall_detector` | BMI 事件链调用，不映射为交通等级 |
| `board_runtime/mr20_radar` | `/root/smartbag/mr20_radar` | controller 内 worker；独立 source/multi-frame 稳定 |
| `board_runtime/cloud_uploader` | `/root/smartbag/cloud-uploader` | 可选独立 service，默认关闭 |
| audio assets | `/root/smartbag/audio` | Rev2 默认启用、optional degrade；只播放 L3/R3/L4/R4 |
| 模型 | `/root/smartbag/models/yolov8n.om` | 正式 NPU 默认；安装时由合法本地文件提供，不进入 Git |
| SS928 ACL adapter | `/root/smartbag/vision/ss928_backend/lib/libsmartbag_ss928_acl.so` | 由仓库源码交叉编译，安装参数 4 提供 |
| 固定 Python | `/root/smartbag/venv` | systemd 直接调用，不依赖 shell activate |
| 双摄配置 | `/etc/smartbag/config.json` | 左右设备、profile、流、PWM、超时和 BLE |
| 硬件 profile | `/etc/smartbag/hardware.json` | Rev2/Legacy 互斥、mux、TM6605、灯光、MR20、输出策略 |
| MR20 配置 | `/etc/smartbag/mr20-radar.json` | UDP 来源、side、目标范围、多帧风险 |
| Cloud 配置 | `/etc/smartbag/cloud-uploader.json` | 默认关闭；secret 只来自环境文件 |
| 双标定 | `/etc/smartbag/calibration-left.json`、`calibration-right.json` | 用户分别实测填写 |
| 统一 pinmux | `/root/smartbag/apply-smartbag-pinmux.sh` | controller 启动前配置 I2C0/UART4/PWM/I2S |
| 轨迹/持久数据 | `/var/lib/smartbag/...` | 卸载时保留 |
| risk CSV/log | `/var/log/smartbag/...` | 左右独立，Git 忽略 |
| systemd | `/etc/systemd/system/smartbag-*.service` | target 要求 safe-off + controller，Wants boot self-test |
| 启动等待报告 | `/run/smartbag/waits/*.json` | required 超时失败，optional 标记 degraded |
| boot self-test | `/var/log/smartbag/boot-selftest/latest.json` | boot ID、service、配置 SHA、commit 和 final |
| Rev2 validation | `/var/log/smartbag/rev2-validation/` | 分阶段自动测试，物理输出需显式允许 |
| 交替 session 清理 | `/root/smartbag/board-deploy/cleanup-alternating-runs.sh` | timer 保留最多 10 个/100 MiB，跳过活动 session |
| journald 限额 | `/etc/systemd/journald.conf.d/smartbag.conf` | 持久 100 MiB、运行时 32 MiB、最长 7 天 |

`smartbag-vision.service` 是单侧诊断 unit，不属于 `smartbag.target`。正式交替 detector 由 controller 子进程监督；`smartbag-alternating-vision.service` 只保留互斥诊断入口。`smartbag-cloud-uploader.service` 也不属于默认 target，云端故障不会阻塞本地告警。IMX347 MIPI preview/VO 只保留在 firmware samples，不加入默认启动链。

旧路径 `/root/dx_gp21_tracker`、`/root/vision_obstacle_tracker`、`/root/smartbag_alert`、`/opt/bmi270_backpack` 不再由脚本创建。升级时先停止旧服务，迁移持久数据并删除旧 unit，避免重复注册 BLE、重复打开相机或同时控制 PWM。

不随部署包分发：`10_archive`、厂商 SDK、系统镜像、`.om`/PyTorch 模型、ARM wheels、原始视频、risk log、设备密码/IP、许可不明音频。仓库分发 ACL adapter 源码，不分发厂商 `libascendcl.so`；交叉编译产物由部署者按板端 SDK 生成并显式传给安装器。
