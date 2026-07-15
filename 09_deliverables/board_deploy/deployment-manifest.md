# 部署内容清单

| 源目录 | 板端目录 | 默认启动方式 |
|---|---|---|
| `06_software/vision_obstacle_tracker` | `/root/smartbag/vision` | controller 监督单摄 detector |
| `board_runtime/smartbag_alert_controller` | `/root/smartbag/controller` | `smartbag-alert.service` |
| `board_runtime/dx_gp21_tracker` | `/root/smartbag/gnss` | controller 子进程，默认 no-BLE |
| `board_runtime/bmi270_backpack` | `/root/smartbag/imu` | controller 子进程，默认 no-BLE |
| audio assets | `/root/smartbag/audio` | 可选，默认关闭 |
| 模型 | `/root/smartbag/models` | 用户单独提供，不进入 Git |
| 配置 | `/etc/smartbag/config.json` | 首次安装复制 example，不覆盖已有配置 |
| 统一 pinmux | `/root/smartbag/apply-smartbag-pinmux.sh` | controller 启动前配置 I2C0/UART4/PWM/I2S |
| 轨迹/标定 | `/var/lib/smartbag/...` | 持久化保留 |

旧路径 `/root/dx_gp21_tracker`、`/root/vision_obstacle_tracker`、`/root/smartbag_alert`、`/opt/bmi270_backpack` 不再由脚本创建。升级时先停止旧服务，复制数据到统一目录，再删除旧 unit，避免同时注册 BLE 或同时控制 PWM。
