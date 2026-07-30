# 模型许可与来源

## `vehicle-detector.om`

- 正式路径：`09_deliverables/board_deploy/models/vehicle-detector.om`
- SHA256：`9e3c448ab7309428ea78cfdc509926404220fa74dd56c89e4995366f5f16af95`
- 上游：Ultralytics YOLO11n Detect，COCO 80 类
- 上游许可：GNU AGPL-3.0-only，或用户另行取得的 Ultralytics Enterprise License
- 本仓库分发方式：AGPL-3.0-only
- 对应源权重：Ultralytics `yolo11n.pt`，本次转换输入 SHA256 为
  `0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1`
- 转换记录：`08_media/models/ss928_yolo11n/conversion-manifest.json`

OM 是面向 SS928V100 的转换产物。仓库提供转换契约、runner 源码和 manifest，
但不包含厂商 SDK、ACL 运行库或禁止再分发的工具链。商业闭源部署应在发布前
确认并取得适用的上游商业授权。

`runner_compatible=true` 仅表示当前 runner 的静态输入、AIPP、输出和后处理契约
与 manifest 一致；真实板端 ACL 加载和检测对比仍标记为 `PENDING`。
