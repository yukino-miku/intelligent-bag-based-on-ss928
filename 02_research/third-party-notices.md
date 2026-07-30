# 第三方来源与分发说明

| 内容 | 来源 | 当前处理 |
|---|---|---|
| 板端功能代码 | `sanda-tt/ss928@59071297e5d8f339332a7234406429f94ffe2570` | 逐文件审计迁移；来源仓库未发现覆盖全部内容的根 LICENSE，仍需仓库所有者确认公开再分发许可 |
| SS928 SDK/MPP Sample | 厂商 SDK | 不复制；只记录外部路径和构建变量 |
| Bosch BMI270 config blob/头文件 | Bosch 驱动包 | 不复制 `bmi270_config.bin` 和厂商头文件；用户按许可自行安装 |
| YOLO 权重、ONNX、OpenVINO、OM | Ultralytics/转换产物 | 不提交；部署时单独提供并遵守模型许可 |
| Ultralytics YOLO11n 候选模型 | `ultralytics/ultralytics`，上游声明 AGPL-3.0 或 Enterprise | PT/ONNX/OM 仅在本地做工程验证；本仓库根许可未确定且未取得独立模型分发依据，状态为 `LICENSE_BLOCKED` |
| AArch64 detection runner/inspector | 本项目源码，使用 Zig 0.16.0 和 SS928 SDK ACL 头文件/stub 构建 | 仅提交本项目生成 ELF；不提交 Zig 工具链、SDK、stub 或板端 `libascendcl.so` |
| 来源 AAC/PCM | 来源仓库构建/部署目录 | 仅保留单套部署 AAC，PCM 中间文件删除；素材许可仍待确认，音频默认关闭，可用生成工具替换为自有素材 |
| 微信/BlueZ/Nordic UART 协议 | 平台和开源生态 | 代码依赖按各自许可安装，不捆绑二进制 |
| MT5710/板端 sample 工具 | 来源仓库 | 只迁移文本源码，作为可选模块；硬件与厂商工具许可需另核验 |

本文件是来源登记，不构成法律意见。任何厂商 SDK、模型、音频或二进制对外发布前都应补齐许可证和再分发授权。

仓库自身尚无经权利人确认的根许可证，见 `LICENSE_STATUS.md`。在根许可和来源授权解决前，GitHub 可见性不等于获得再分发授权。
