# 第三方来源与许可说明

本仓库从 `sanda-tt/ss928@59071297e5d8f339332a7234406429f94ffe2570` 选择性迁移了项目代码、测试、硬件说明、CAD 和实板经验。来源仓库根目录未提供可覆盖全部内容的明确统一许可证，因此本次迁移不代表对厂商 SDK、sample、模型、音频、文档或二进制拥有再分发许可。

未纳入 Git 的内容包括：SS928/HiSilicon SDK 与镜像、在线仓库镜像、厂商 PDF/压缩包、模型权重/ONNX/OM、Git LFS 缺失对象、BMI270 配置 blob、编译产物、运行日志、原始校准数据和含设备密码/IP 的 handoff 原文。完整文件级决定和 SHA-256 见 `00_admin/sanda-full-file-manifest.csv`。

已迁移源码中的原作者文件头予以保留。`05_firmware/ss928/tsensor` 的源文件带原作者/站点标记，但未见独立许可证；对外再分发或产品使用前必须向权利人确认。部署音频包含来源项目的提示音，仅默认关闭；公开发布前同样需要确认音频素材许可，或使用 `06_software/tools/audio_prepare` 生成自有素材替换。

Ultralytics、OpenCV、OpenVINO、BlueZ、CloudBase、微信小程序 SDK、Nordic UART Service、SS928 ACL/MPP/SVP 等依赖遵循各自上游许可与服务条款。本仓库不把 OpenVINO 视为 SS928 NPU，也不附带厂商运行库。

当前 YOLO11n PT/ONNX/OM 候选来自 Ultralytics 生态，上游声明 AGPL-3.0 或 Enterprise 许可。由于本仓库自身没有经权利人确认的根许可证，也没有记录可覆盖该候选模型的独立商业授权，候选模型状态为 `LICENSE_BLOCKED`，不进入 Git 或 RC Release。仓库内 AArch64 runner/inspector 由本项目源码构建，但构建所用 SS928 SDK 头文件/stub 和板端 `libascendcl.so` 不随仓库再分发。

更细的依赖登记见 `02_research/third-party-notices.md`。本文件是工程清单，不构成法律意见。
