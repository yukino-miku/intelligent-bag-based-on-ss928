# 板端脚本说明

统一安装、启动和卸载入口位于 `09_deliverables/board_deploy`。本目录不再为每个软件模块维护互相矛盾的 `/root/...` 路径。正式安装前先运行 `preflight.sh`，再由 `install.sh` 安装 systemd unit 和统一配置。
