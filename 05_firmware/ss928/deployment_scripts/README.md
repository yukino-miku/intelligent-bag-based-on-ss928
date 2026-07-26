# 板端辅助配置

正式 install/start/upgrade/uninstall 入口位于 `09_deliverables/board_deploy`。本目录只保留硬件初始化辅助文件：

- `ws73-bluetooth-module-start.sh`：在 `/opt/sample/ws73` 或 `WS73_MODULE_DIR` 加载 `plat_soc.ko`/`ble_soc.ko`，等待 `hci0`；由可选 `smartbag-ws73.service` 调用。
- `network/20-mr20-radar.network.example`：MR20 独立网口示例，含历史 IP，仅作模板，不由安装脚本自动复制。

应用 networkd 示例前必须根据当前 interface/IP/路由修改，避免与电脑管理网或另一网口形成同网段冲突。WS73 service 只加载模块，BlueZ/NUS 仍由系统 `bluetooth.service` 与 SmartBag Controller 管理。
