# 第三方来源与许可说明

本仓库原创代码、文档和生成资产按根目录 `LICENSE` 的 GNU AGPL-3.0-only 分发。该选择不会改变第三方材料自身许可，也不构成法律意见。

## 选择性迁移内容

项目从 `sanda-tt/ss928` 的 `codex/dx-gp21-tracker` 等历史分支选择性迁移过板端源码、测试、硬件说明和工程经验。来源仓库没有一个可覆盖全部内容的统一根许可证，因此只保留经文件级审计、与本项目硬件相关且无明显再分发限制的源码/说明；原文件头继续保留。完整决策见 `00_admin/sanda-full-file-manifest.csv` 和 `00_admin/merge-manifest.md`。

未分发内容包括：SS928/HiSilicon SDK、MPP/ACL 二进制与系统镜像、交叉工具链、厂商 PDF/压缩包、在线仓库副本、BMI270 vendor blob、WS73 固件、板端备份、日志、真实标定、用户数据和凭据。`libascendcl.so` 由匹配板端镜像提供。

## 模型

`vehicle-detector.om` 来源于 Ultralytics YOLO11n Detect/COCO80 转换链。本仓库及该转换产物按 AGPL-3.0-only 分发；使用者也可以自行取得适用的 Ultralytics Enterprise License。闭源/商业使用必须自行核对上游条款。来源、哈希和转换记录见 `MODEL_LICENSES.md` 与模型 manifest。

## 音频

部署 AAC 由仓库脚本使用正弦波确定性生成，不含录音、语音、音乐或第三方采样。详情见 `AUDIO_LICENSES.md`。

## 可选依赖

Python、OpenCV、NumPy、Ultralytics、BlueZ、dbus-python、PyGObject、FFmpeg、微信小程序/CloudBase、Nordic UART Service 约定及其他依赖遵循各自上游许可和服务条款。仓库不再分发这些依赖的二进制副本。

`05_firmware/ss928/tsensor` 等保留原作者标记但缺少独立清晰许可证的厂商相关样例不进入正式安装主路径；对外产品化前应取得相应权利人确认。
