# 第三方依赖审计

| 组件 | 用途 | 仓库处理 | 许可/限制 |
|---|---|---|---|
| Ultralytics YOLO11n | PC 检测与 SS928 OM 来源 | 正式 OM、契约和转换记录入库；PT/ONNX 不作为运行依赖 | 项目按 AGPL-3.0-only 分发，或部署方另购 Enterprise License |
| OpenCV / NumPy | 图像采集、预处理和工具 | 通过系统/包管理器安装 | 遵循各自上游许可 |
| SS928 ACL/MPP/SDK | NPU 和硬件运行时 | 不入库；来自匹配板端镜像 | 厂商条款，禁止假定可再分发 |
| BlueZ/dbus/PyGObject | BLE NUS | 通过板端系统安装 | 上游许可 |
| 微信小程序/CloudBase | 手机端与可选云功能 | 项目源码入库，AppID/secret 不入库 | 平台服务条款 |
| FFmpeg | 确定性生成 AAC 的构建工具 | 不入库 | 取决于使用者安装的构建选项 |
| `sanda-tt/ss928` 迁移内容 | GNSS、BMI270、告警、工具和文档 | 文件级选择迁移，保留原头 | 来源无统一根许可，产品化前复核 |
| 厂商 PDF/SDK/blob/固件/镜像 | 参考或硬件初始化 | 不分发，只在资产审计登记哈希 | 再分发许可未建立 |

正式分发边界以根 `THIRD_PARTY_NOTICES.md`、`MODEL_LICENSES.md`、`AUDIO_LICENSES.md` 和 `00_admin/local-deployment-asset-inventory.*` 为准。
