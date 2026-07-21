# SS928 视觉运行依赖审计

审计日期：2026-07-19。目标环境为 SS928V100、Ubuntu 22.04.1、aarch64、Python 3.10.12。

## 当前板端结果

| 项目 | 当前结果 | 来源/安装方式 |
|---|---|---|
| Python | 3.10.12 | 系统 `/usr/bin/python3` |
| NumPy | 板端验收时需复查 | APT 候选 1.21.5 |
| OpenCV | 板端验收时需复查 | APT 候选 4.5.4 |
| torch | 未安装，BLOCKED | 本地未找到已验证的 aarch64 CPython 3.10 wheel |
| torchvision | 未安装，BLOCKED | 必须与 torch ABI 配套 |
| Ultralytics | 未安装，BLOCKED | 依赖可用的 torch/torchvision |
| lap | 未安装，BLOCKED | 本地未找到已验证 wheel，源码构建尚未验证 |
| pip | 未安装 | APT 候选 22.0.2 |

`10_archive/ss928/09. 进阶功能开发/02.Opencv移植.zip` 是 OpenCV 4.5.5 源码，不是可直接安装的 Python wheel。仓库不复制 SDK、wheel 或大型二进制。

## 安装策略

1. 先运行 `install-board-cpu-deps.sh` 安装系统 OpenCV、NumPy、v4l2 工具和基础服务；`ss928_om` 后端只需要其中的 OpenCV/NumPy，不需要 torch 系列。
2. torch/torchvision/Ultralytics/lap 仅从经过 SHA256 记录、确认 `linux_aarch64` 和 `cp310` ABI 的离线 wheelhouse 安装。
3. `install-board-deps-offline.sh` 强制 `--no-index`，不会静默下载不匹配版本。
4. 安装后必须运行 `check-runtime-deps.sh /etc/smartbag/config.json`；它会根据 `detector_backend` 选择 NPU 或 Ultralytics 依赖门禁，任何 import 或 ACL adapter 检查失败都不能记为板端 YOLO 已通过。

PC 端已验证版本记录在 `06_software/vision_obstacle_tracker/requirements-pc.txt`。这些版本不能直接等同为板端版本。
