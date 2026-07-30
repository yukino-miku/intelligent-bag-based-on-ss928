# Clone 与安装就绪度

2026-07-30 使用 GitHub HTTPS 在原工作区之外全新浅克隆 `main`，并从同一远端 fast-forward 到验收提交 `36ae2427ee05accdd30626a31ac7d12200a87096`。验收没有复制 ignored 文件、`08_media`、`10_archive`、本地 SDK、虚拟环境、手工模型或 runner。

## 验收结果

| 项目 | 状态 | 证据 |
|---|---|---|
| 源码、配置、systemd | READY | 全部由 Git 取得；CI 和静态检查通过 |
| 正式车辆 OM | READY_STATIC | SHA256 `9e3c448ab7309428ea78cfdc509926404220fa74dd56c89e4995366f5f16af95` |
| AArch64 runner | READY_STATIC | SHA256 `332c792dc7a64190e182f6260edb455668e1885e883a0e48c794728eed024737`；ELF/contract 通过 |
| full/radar-only mock | PASS | 两种模式均安装成功；radar-only 继续使用共享 RiskModel |
| 重复安装与卸载 | PASS | 重复安装保留配置；卸载保留配置和事件数据 |
| 离线发布包 | PASS | SHA256 校验通过，包含正式 OM/runner，不含 `08_media/10_archive` |
| API 安全 | READY_STATIC | 安装生成管理/只读 Token；公网无认证配置被拒绝 |
| ACL 与 OM 实板推理 | PENDING | 必须在匹配 SS928 镜像上验证 descriptor 和检测结果 |
| 相机、双 MR20 与融合标定 | PENDING | 首装发现及标定工具已交付，仍需当前硬件实测 |
| 30 分钟、reboot、独立供电 | PENDING | 不用历史测试冒充 RC2 实板验收 |

## 最终状态

- `CLONE_INSTALL_READY=true`
- `BOARD_INSTALL_VERIFIED=false`
- `POWER_ONLY_AUTOSTART_READY=false`

板端最终验收命令：

```sh
sudo ./validate-on-ss928.sh --full --duration 30m
```
