# SS928 NPU 后端状态

更新时间：2026-07-22

`Ss928OmBackend` 通过仓库内 C ABI 调用 ACL，模型和 dataset/device buffer 在进程内常驻。当前支持两种已声明输入契约：静态 AIPP NV12，以及普通 RGB CHW/HWC tensor。输出只接受 FP32 `1x84x8400`，shape、dtype 或 byte size 不匹配时立即拒绝启动。

已由本地测试覆盖：letterbox、NV12 UV 排列、RGB tensor、类别前置过滤、YOLO 解码、class-aware NMS、原图坐标恢复、fake ACL runtime、tracker、公共测距/风险/overlay 链路和资源关闭。

正式默认仍是已配置的 `yolov8n.om`。候选 `yolo11n_ss928.om` 已生成，SHA256 为 `9e3c448ab7309428ea78cfdc509926404220fa74dd56c89e4995366f5f16af95`，但没有本轮真实板端目标命中和长测证据，因此不得覆盖默认模型。

本轮未完成：ACL 元数据读取、单帧/100 帧、左右交替、真实目标、overlay、30 分钟、RSS/CPU/温度和模型释放的实板对比。原因是 `BOARD_CONNECTION_BLOCKED`。当前不能声称 YOLO11 比 YOLO8 更快或更准。
