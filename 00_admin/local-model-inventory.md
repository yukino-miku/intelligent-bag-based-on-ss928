# 本地模型与历史视觉资产清单

审计日期：2026-07-28。机器可读清单见 [local-model-inventory.json](local-model-inventory.json)。本清单覆盖当前 HEAD、未跟踪和忽略文件、Git LFS、全部本地/远程分支、Git 历史、`08_media`、`10_archive`、同级 `备份` 与 `tmp`。当前仓库没有 Git LFS 对象。共发现并逐路径登记 21 个 PT/ONNX/OM 文件；另有 16 个 `.bin` 经核对是 CMake 编译器探测输出、ACT 示例输入张量或第三方雷达固件，不是视觉模型，已在 JSON 的 `excluded_binary_groups` 中分组登记。

## 结论

- PC 视觉继续复用 YOLO11n COCO 80 类模型；它包含 `bicycle`、`motorcycle`、`car`、`truck`、`bus`，无需另训纯分类网络。
- 首选 SS928 候选为 `08_media/models/ss928_yolo11n/yolo11n_ss928.om`，SHA256 为 `9e3c448ab7309428ea78cfdc509926404220fa74dd56c89e4995366f5f16af95`。
- 该 OM 已通过 ONNX checker 和 ATC 编译，输入源为 `1x3x640x640`，输出为 `1x84x8400`；但静态 AIPP 是 `RGB_PLANAR`，当前正式 runner 固定要求 NV12/YUV420SP，因此目前不能标记为直接部署。
- 归档中的 `yolo11s.om` 是第二候选，但尚缺 ACL I/O、后处理契约、许可来源和已知图片结果核验。
- 历史 `/root/smartbag/models/yolov8n.om` 有 NPU 时延记录：推理约 25 ms、后处理约 17 ms；历史测试没有得到可信目标框，不能当作识别正确性证据。

## 关键资产

| 资产 | SHA256 | 用途 | 当前判断 |
|---|---|---|---|
| `08_media/models/ss928_yolo11n/yolo11n_640.pt` | `0ebbc80...7644ee1` | PC Ultralytics、导出源 | PC 可用 |
| `08_media/models/ss928_yolo11n/yolo11n_640.onnx` | `aa916c4...ab51116` | OM 转换源 | ONNX checker 通过 |
| `08_media/models/ss928_yolo11n/yolo11n_ss928.om` | `9e3c448...16af95` | SS928 候选 | ATC 通过，runner 输入不兼容，待实板 |
| `10_archive/.../ModelZoo/model/yolo11s.om` | `19415b1...981c0` | ModelZoo 备用 | 接口和识别均待验证 |
| `备份/.../yolo11n_imgsz512.onnx` | `31f6180...b058` | 历史 C-port | 可回放，需重新转 OM |
| `备份/.../yolo11n.onnx` | `80bc55a...720c` | 历史 1024 ONNX | 可回放，当前板端过重 |

其他归档 OM 分别用于分割、姿态、人脸、OCR、分类、特征点、人群计数和超分，不符合本项目车辆框检测输出契约，未选用。

## 审计证据

- `git status --short --ignored`：模型主要位于被忽略的 `08_media/` 和 `10_archive/`。
- `git lfs ls-files`：空；当前没有模型由 LFS 跟踪。
- `git log --all --name-only -- '*.pt' '*.onnx' '*.om'`：历史包含 YOLO11n PT/ONNX、多个 SDK 示例 OM 和来源仓库 YOLOv8n。
- `08_media/board-live/status.json` 与 `08_media/board-npu-validation/`：证明历史 ACL runner 跑过，不证明识别正确。
- `08_media/models/ss928_yolo11n/conversion-manifest.json`：记录新 YOLO11n 的来源哈希、输入输出、量化图片数、ATC PASS 和板端 ACL PENDING。

## 部署约束

正式名称统一为 `/root/smartbag/models/vehicle-detector.om`。安装时通过 `SMARTBAG_MODEL_SOURCE=/absolute/path/model.om` 显式选择已经验收的来源；未设置该变量时安装器不会从 `08_media` 自动取候选，也不会覆盖 `/root/smartbag/models` 中已有正式模型。安装器不会把占位文件或假结果当作模型。

当前仍需实板完成：ACL descriptor 检查、RGB_PLANAR 输入适配验证、同图 PT/ONNX/OM 检测对齐、双 USB 快照、长期稳定性和温度资源测试。
