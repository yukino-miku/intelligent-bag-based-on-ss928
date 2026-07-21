# SS928 OM 后端状态

状态：**代码已实现并完成 ARM64 交叉编译，真实双摄连续运行仍需板端验收。**

## 已确认资源和模型契约

- 板端 ACL 运行库：`/opt/lib/npu/libascendcl.so`，运行时使用 `LD_LIBRARY_PATH=/opt/lib/npu:/opt/lib`。
- 板端模型：`/opt/sample/yolov8/yolov8n.om`，此前记录的 SHA256 为 `7010d928c2ce9675ea38b6ee353f1c4fcd4ec648a335d3735d85f2e0313d030b`。
- SS928 SDK AIPP 配置为 `RGB_PLANAR`，输入由 ACL tensor 描述决定，目前适配器支持 NCHW/CHW 和 NHWC/HWC 识别。
- 已验证目标输出契约为单输出、FP32、`1x84x8400`；类别按 COCO 80 类解释。
- 之前板端单图执行记录约 25.44 ms，但该数据不是完整实时链路 FPS。

## 当前实现

1. `ss928_backend/native/libsmartbag_ss928_acl.so` 提供稳定 C ABI，模型和 input/output dataset 在进程生命周期内常驻，不再逐帧读写临时图片。
2. Python `Ss928OmBackend` 完成 BGR USB 帧的 letterbox、RGB/layout 转换、ACL 内存推理、类别前置过滤、NMS 和原图坐标恢复。
3. NPU 结果使用不依赖 torch/Ultralytics 的便携结果结构和轻量 IoU tracker；交替双摄左右 tracker 完全独立。
4. 后续测距、稳定 ID、速度、Future Conflict Gate、风险、多帧 stabilizer、haptic level、risk CSV 和 overlay 继续复用原有实现。
5. `performance.csv` 分开记录预处理、NPU 执行和检测后处理时间。

## 已知运行时边界

- 当前板端 ACL 版本在完成模型卸载后调用 `aclFinalize()` 会异常。适配器仍正常卸载 model/dataset/buffer，但把 ACL 全局资源的最终回收交给 detector 进程退出，避免在服务停止时崩溃。
- `.om` 不是通用文件。模型输入类型、布局或输出大小与上述契约不一致时，后端会拒绝启动，不能静默猜测。
- NPU 路径仍需要板端 Python 3 的 `numpy` 和 `cv2`，但不需要 torch、torchvision、Ultralytics 和 lap。
- OpenVINO 仅用于 PC/通用 CPU 路径，不代表 SS928 NPU。

## 板端验收项

1. 核对实际 model tensor 元数据和 AIPP 输入布局。
2. 用同一张快照比较 ModelZoo 文件样例与实时内存后端的检测结果。
3. 连续运行两路 USB 交替采集，确认 model 只加载一次、左右 ID 不串线、overlay 非空。
4. 记录预处理、NPU、NMS、tracker、risk、overlay、JPEG 和端到端观测间隔。
5. 完成短测后再做 30 分钟稳定性和摄像头断开重连测试。
