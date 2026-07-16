# 目录清理报告

清理前已使用 `rg` 检查 import、app.json、Makefile、shell、systemd、README 和测试引用。历史文件可从 Git 恢复。

## 来源仓库未迁移

- `agent.md`、完整 `skills/` 和 `agents/openai.yaml`：代理元数据，不是运行时。
- `ld2417-radar-web`、`radar_uart_test`：当前纯视觉路线不采用雷达。
- SDK、在线仓库副本、二进制、`.o`、`__pycache__`、日志：体积、许可或可再生成原因。
- `calibration_data/*.csv`：原始采集不适合公开仓库，只迁分析文档。
- `bmi270_config.bin`：第三方 blob，许可不明确。
- PCM/AAC 和 audio build/deploy 重复副本：素材许可不明确且重复；保留生成工具，音频默认关闭。
- 小程序 cloudfunctions、example、placeholder、默认图片、private config：未被 app.json/当前页面引用或包含本地信息。

## 目标仓库清理

- 删除活动目录 `06_software/radar_visualizer` 及旧实现计划，结束活动雷达路线。
- 删除仓库跟踪的 YOLO `.pt`/`.onnx`，模型由部署阶段提供。
- 删除本地 `risk_log*.csv`、测试视频、build/dist、缓存和临时日志；`08_media`、`10_archive` 保留本地但 Git 忽略。
- 删除无引用的根目录临时文本文件。

`.gitignore` 使用精确规则保留正常测试 fixture，不全局忽略所有 CSV/JSON。

清理后扫描未发现活动目录中的 `.pyc`、原始 calibration CSV、`.om`、YOLO 权重、ONNX、厂商 `.bin` 或 C 构建 `.o`。
