# Clone 与安装就绪度

当前静态候选已经包含普通 Git clone 所需的源码、正式 OM、AArch64 runner/inspector、manifest、配置、相机发现、MR20 健康检查、标定向导、systemd、安装器和 License。正式模型与 runner 的 SHA/架构/静态 I/O 契约通过；厂商 ACL runtime 由匹配板端镜像提供。

## 验收项目

| 项目 | 当前状态 | 证据 |
|---|---|---|
| 源码、配置、systemd | READY | Git tracked；Python/Node/native/Shell/JSON 测试覆盖 |
| 正式车辆 OM | READY_STATIC | Git tracked；SHA256 `9e3c448a...f16af95`；AGPL-3.0-only |
| AArch64 runner/inspector | READY_STATIC | Git tracked；ELF/SHA/contract manifest 通过 |
| ACL 动态库 | BOARD_IMAGE_REQUIRED | 不允许从仓库分发，preflight 检查 `libascendcl.so` |
| 左右相机 | FIRST_INSTALL_DISCOVERY | 安装器交互确认，生成 hardware-discovery 和 udev 链接 |
| 双 MR20 | FIRST_INSTALL_VALIDATION | 配置已跟踪，live check 要求合法帧和完整扫描 |
| 融合标定 | FIRST_INSTALL_CALIBRATION | 误差与硬件身份合格才启用 full |
| 安装/升级/卸载 | READY_STATIC | full/radar-only mock、重复安装、配置与事件保留通过 |
| API 安全 | READY_STATIC | 自动生成管理/只读 Token，公网无认证被拒绝 |
| 离线包 | PENDING_FINAL_COMMIT | 构建脚本已通过本地静态验证，最终 commit 后重建 |
| 真机 ACL/外设/30 分钟 | PENDING | 不用历史结果冒充 RC2 验收 |
| reboot/独立供电 | PENDING | 必须在板端另行执行 |

## 状态规则

- 最终 GitHub HTTPS 干净 clone 完成资产校验、full/radar-only mock、重复安装、卸载保留和 release 包检查后，设置 `CLONE_INSTALL_READY=true`。
- `BOARD_INSTALL_VERIFIED` 只有当前 RC2 在真实 SS928 完成安装、相机、双 MR20、OM、标定、输出与 30 分钟长测后才能为 true。
- `POWER_ONLY_AUTOSTART_READY` 只有 reboot 后拔除电脑并完成独立供电冷启动后才能为 true。

最终验收命令：

```sh
git clone https://github.com/yukino-miku/intelligent-bag-based-on-ss928.git
cd intelligent-bag-based-on-ss928
sudo ./install-on-ss928.sh --interactive
sudo ./validate-on-ss928.sh --full --duration 30m
```
