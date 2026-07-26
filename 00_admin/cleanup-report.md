# 目录清理与去重报告

清理决定以 `sanda-full-file-manifest.csv` 为准。删除/不迁移前检查了 Git 引用、Python import、app.json、Makefile、shell、systemd、README 和测试；来源历史仍可由固定 SHA 恢复。

## 未复制到正式仓库

- 来源根目录、`work/` 外壳、完整 `skills/` 包装和 `agents/openai.yaml`：不建立第二套目录和代理元数据；仅迁移有效脚本/参考内容。
- SDK、在线仓库镜像、厂商 sample 大树、PDF/压缩包/镜像：以 manifest 和来源 SHA 索引，避免许可、体积和重复问题。
- 5 个缺失 Git LFS 对象：仅记录 pointer OID/声明大小，标为 `BLOCKED`。
- `handoff.md`：含设备 IP/密码，标为 `BLOCKED`，不复制原文。
- `.om`/`.onnx`/`.pt`、BMI270 config blob、`.ko`/`.o`/可执行文件、raw output、NV12/图片样本、日志、校准 CSV：二进制许可不明、运行数据或可重建产物。
- 小程序 quickstartFunctions、example、默认 CloudBase 图片/组件、private config：脚手架或本地配置；有效告警逻辑迁入正式 `pages/alarms`。
- 旧 VOT live pipeline、交替采集入口和 controller dry-run shim：由现有固定双 detector、Python tracker/risk 和 `c_port` 覆盖，不恢复为正式入口。
- 来源旧 systemd/start 脚本：路径和硬件所有权与统一 `/root/smartbag` 冲突，功能合并进 `09_deliverables/board_deploy`。
- 重复 MR20 parser、MT5710 supervisor、BMI service 和音频 build/deploy：只保留当前模块与单套最终 AAC；PCM 中间文件删除。
- 来源提交自动生成的 DOCX：只保留 `build_submission_doc.py`。

## 正式保留或迁移

- MR20 有效 parser/worker/config/test 合并到 `board_runtime/mr20_radar`，默认关闭；这不恢复旧 `radar_visualizer`，也不修改视觉风险模型。
- CloudBase 两套正式函数及必需 `lib/*.js`、姿态/告警/remote 小程序页面和测试。
- TCA9548A/TM6605、PWM 灯、WS73、MT5710、Tsensor、CAD、NPU 合约/预处理/解码源代码和有效诊断文档。
- L1-L4/R1-R4 与 `bad` 的最终 AAC/播放提示；音频默认关闭，公开发布前仍需确认素材许可。
- `10_archive/sanda_ss928/README.md` 仅保存来源索引，不复制来源大树。

## 目标仓库清理规则

- `08_media` 继续忽略；`10_archive` 只允许提交来源索引 README。
- 忽略 risk log、视频、模型、OpenVINO/OM、build/dist、Python cache 和板端日志。
- 根 `lib/`/`bin/` 规则已改为根路径限定，避免误忽略 CloudBase 函数源码。
- 提交前删除 `__pycache__`、`.pyc`、NPU native build 和本地测试日志，并运行 secret、大文件、重复哈希与 `git diff --check` 扫描。

## 提交前扫描结果

- 正式树（排除 manifest、`08_media`、`10_archive`）共哈希 363 个文件，发现 7 组精确重复；均为需要同步的 Controller/部署配置、左右校准模板、左右音频播放提示或相同的小程序空页面配置，没有重复运行入口。
- 唯一超过 5 MiB 的待提交文件是约 13 MiB 的逐文件 manifest；未发现模型、视频、SDK、日志或构建二进制进入 Git。
- secret 扫描未发现板端密码、Cloud token、手机号或当前板 IP；MR20 配置中的 `192.168.1.200/201` 是雷达设备地址，板端监听使用 `0.0.0.0`，networkd 文件仅为不自动安装的示例。
