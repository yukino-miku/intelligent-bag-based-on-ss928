# SmartBag v1.0.0 RC1 发布审计

## Git 基线

- 开始提交：`e2c524b69b1613c47921923c7bf3f4dae68c5980`。
- 开发分支：`agent/radar-primary-vision-class-fusion`。
- Draft PR：`#7`。
- 审计时默认分支：`agent/ss928-board-integration`，本轮不合并，因为完整模型和实板验收尚未完成。
- Git LFS：无跟踪对象；stash：空；发布所需 runner 直接进入 Git。

## 本地资产扫描

逐文件清单见 `local-deployment-asset-inventory.csv/json`：共 1,495 个候选文件、8,256,821,071 bytes、21 个模型、524 个 ELF。1,058 个候选因许可证或厂商/备份属性标记为不分发。路径使用匿名 root，不记录电脑用户名和绝对路径。

选中的本地候选为 YOLO11n PT/ONNX/OM。PT 和 ONNX 的车辆检测同图比较通过；OM 仅有 ATC 产物，缺 SS928 descriptor/检测对齐，且模型与仓库根许可未解决，因此不上传。

## 发布资产

| 资产 | 大小 | SHA256 | 分发 |
|---|---:|---|---|
| `09_deliverables/board_deploy/bin/aarch64/ss928_detection_runner` | 505,464 | `0be03a9772e511a57885731c2d0570071077b638c263af5e0a39f680205e93af` | Git，项目源码构建；ACL runtime 不随仓库分发 |
| `09_deliverables/board_deploy/bin/aarch64/om_inspect` | 477,224 | `34c944a3c7b2c62042ef2077042e1d0bf3fc5798b8d0932e29ffd497faa2cc0b` | Git，项目源码构建；ACL runtime 不随仓库分发 |
| `vehicle-detector.om` 候选 | 3,426,459 | `9e3c448ab7309428ea78cfdc509926404220fa74dd56c89e4995366f5f16af95` | 不上传，`LICENSE_BLOCKED`、`BOARD_VALIDATION_PENDING` |

## 验证结论

- GitHub 远程浅克隆成功，remote clone 不包含本地 ignored 资产。
- Python 385 项、Node 12 项、NPU C++ 4 项、C 核心 1 项、C++ backend 1 项通过。
- compileall、38 JavaScript、42 JSON、30 Shell、runner 架构/SHA、凭据扫描、mock install 和离线包策略通过。
- `CLONE_INSTALL_READY=false`：完整视觉模式缺合法且板端验收通过的模型。
- `BOARD_INSTALL_VERIFIED=false`：没有在当前 SS928 接线上执行安装和硬件 preflight。
- `POWER_ONLY_AUTOSTART_READY=false`：没有 reboot 与独立供电冷启动证据。
