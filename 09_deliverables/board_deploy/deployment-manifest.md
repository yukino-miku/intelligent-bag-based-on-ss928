# 部署内容清单

| 源目录 | 板端目录 | 默认启动方式 |
|---|---|---|
| `06_software/vision_obstacle_tracker` | `/root/smartbag/vision` | 共享 RiskModel、DetectorBackend 和 SS928 OM runner；PC 纯视觉模式保留回归 |
| `board_runtime/smartbag_alert_controller` | `/root/smartbag/controller` | `smartbag-alert.service`，统一 BLE/TM6605/灯/音频/MR20/GNSS/IMU |
| `board_runtime/common` | `/root/smartbag/common` | controller 资源采样与公共协议 |
| `board_runtime/dx_gp21_tracker` | `/root/smartbag/gnss` | controller 子进程，默认 no-BLE |
| `board_runtime/bmi270_backpack` | `/root/smartbag/imu` | controller 子进程，默认 no-BLE |
| `board_runtime/imu_fall_detector` | `/root/smartbag/imu_fall_detector` | BMI 事件链调用，不映射为交通等级 |
| `board_runtime/mr20_radar` | `/root/smartbag/mr20_radar` | Controller 内双 worker，输出每轮完整 RadarScan |
| `board_runtime/radar_vision_fusion` | `/root/smartbag/radar_vision_fusion` | 轨迹、交替快照、投影、关联、绑定、共享风险、回放和调试 API |
| `board_runtime/cloud_uploader` | `/root/smartbag/cloud_uploader` | BMI/GNSS 异步调用，失败不阻塞 |
| `board_runtime/mt5710_connectivity` | `/root/smartbag/connectivity` | `smartbag-connectivity.service`，只管理 NCM |
| `board_runtime/temperature` | `/root/smartbag/temperature` | `smartbag-temperature.service`，可选 |
| audio assets | `/root/smartbag/audio` | 可选，默认关闭 |
| 模型 | `/root/smartbag/models` | 用户单独提供，不进入 Git |
| 双摄配置 | `/etc/smartbag/config.json` | 左右设备、profile、流、TM6605/灯、MR20、模块、超时和 BLE |
| root-only 环境 | `/etc/smartbag/smartbag.env` | MT5710、WS73 路径、Cloud token、告警号码 |
| 视觉标定 | `/etc/smartbag/calibration-left.json`、`calibration-right.json` | 旧纯视觉回归使用 |
| 融合标定 | `/etc/smartbag/fusion-left.json`、`fusion-right.json` | 用户分别实测相机内参、位姿和雷达到相机外参 |
| 统一 pinmux | `/root/smartbag/apply-smartbag-pinmux.sh` | controller 启动前配置 I2C0/UART4/灯 PWM/I2S |
| WS73 loader | `/root/smartbag/ws73-bluetooth-module-start.sh` | `smartbag-ws73.service`，模块存在时可选加载 |
| 轨迹/持久数据 | `/var/lib/smartbag/...` | 卸载时保留 |
| risk CSV/log | `/var/log/smartbag/...` | 左右独立，Git 忽略 |
| systemd | `/etc/systemd/system/smartbag-*.service` | `smartbag.target` 默认只要求统一 alert/fusion Controller；旧 video gateway 手动回归 |

`smartbag-vision.service` 是单侧诊断 unit，不属于 `smartbag.target`。IMX347 MIPI preview/VO 只保留在 firmware samples，不加入默认启动链。

旧路径 `/root/dx_gp21_tracker`、`/root/vision_obstacle_tracker`、`/root/smartbag_alert`、`/opt/bmi270_backpack` 不再由脚本创建。升级时先停止旧服务，迁移持久数据并删除旧 unit，避免重复注册 BLE、重复打开相机或同时控制 PWM。

不随部署包分发：来源镜像、厂商 SDK、系统镜像、`.om`/PyTorch 模型、ARM wheels、原始视频、risk log、设备密码/IP。`ss928_backend` 源码和持久快照 bridge 会随 vision 复制，但合法车辆模型、ACL runtime、真实检测正确性和长期性能仍需单独验收。
