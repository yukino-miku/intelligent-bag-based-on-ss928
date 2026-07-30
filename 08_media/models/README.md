# SS928 模型文件

本目录保存允许随当前 Git 分支提交的 SS928 模型候选。个人测试视频、检测输出、板端运行日志、厂商 SDK、ACL runtime、工具链和构建缓存仍由根目录 `.gitignore` 排除。

## YOLO11n 车辆检测候选

- 主文件：`ss928_yolo11n/yolo11n_ss928.om`
- ATC 原始产物副本：`ss928_yolo11n/om-artifact/yolo11n_ss928.om`
- SHA256：`9e3c448ab7309428ea78cfdc509926404220fa74dd56c89e4995366f5f16af95`
- 大小：`3,426,459` bytes
- 输入契约：RGB planar FP32，`1x3x640x640`
- 输出契约：FP32，`1x84x8400`
- 目标 SoC：SS928V100

两个 OM 路径内容和哈希完全相同。保留原始产物路径是为了核对转换记录，正式部署来源使用顶层主文件。

该模型是候选产物，不代表已经通过 SS928 实板识别验收。正式启用前仍须在目标板读取 ACL descriptor，并使用已知图片完成 OM 与 PT/ONNX 检测结果对齐。部署状态以 `09_deliverables/board_deploy/models/vehicle-detector.manifest.json` 为准。

模型来自 Ultralytics YOLO11n 生态，上游声明 AGPL-3.0 或 Enterprise 许可。仓库根许可和最终分发方式仍需项目权利人确认，详见根目录 `LICENSE_STATUS.md` 与 `THIRD_PARTY_NOTICES.md`。
