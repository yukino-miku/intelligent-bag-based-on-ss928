# 音频资产许可

`09_deliverables/board_deploy/assets/audio` 下的 L1-L4、R1-R4 和 `bad` AAC
均由仓库脚本 `06_software/tools/audio_prepare/generate_alert_tones.py` 使用正弦波
确定性生成，不包含录音、音乐、语音或第三方采样素材。

这些生成音频与项目自有源码一并按仓库根目录 `LICENSE` 的 AGPL-3.0-only
条款分发。FFmpeg 仅作为构建工具使用，不随仓库或发布包分发；使用者安装的
FFmpeg 仍受其自身构建选项和许可证约束。
