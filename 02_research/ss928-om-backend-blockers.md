# SS928 OM 后端阻塞项

状态：**BLOCKED，未实现 `Ss928OmBackend` 实时 USB 摄像头推理。**

## 已确认资源

- 板端存在 `/opt/lib/npu/libascendcl.so` 及 ACL 运行库；运行时需包含 `LD_LIBRARY_PATH=/opt/lib/npu:/opt/lib`。
- 板端存在 `/opt/sample/yolov8/yolov8n.om`，SHA256 为 `7010d928c2ce9675ea38b6ee353f1c4fcd4ec648a335d3735d85f2e0313d030b`。
- `10_archive/.../ModelZoo/model/yolo11s.om` 大小 10,368,919 字节，SHA256 为 `19415B173C90122089F0A63D1CB54D9EBA2904905438A980CB4E44F17C8981C0`。
- ModelZoo 文档给出 `1x3x640x640` 输入和 `FP32 84x8400` 输出，并有基于 ACL/common 库的离线 C++ 文件列表样例。

## 仍缺少的可验证接口

1. 板端缺少与现有镜像完全匹配的 ACL 开发头文件、CMake/交叉工具链和可重建的 `infer_common` 安装说明。
2. 现有 `/opt/sample/yolov8/sample_yolov8_*` 可执行文件绑定 IMX347/OS04A10/OS08A20/SC450AI MIPI sensor 流程，不是通用 USB MJPEG/内存帧 API。
3. 离线 ModelZoo 示例输入是文件列表，尚未提供可复用的单帧内存输入、输出生命周期和线程安全约定。
4. `yolov8n.om` 的实际输入色彩、缩放/letterbox、AIPP 参数、类别映射和 NMS 责任边界尚未从板端运行结果核对。
5. 当前没有能在 Python 进程中安全调用的 ACL binding；直接用 `ctypes` 猜测 ABI 风险不可接受。

## 后续所需

- 与板端 `/opt/lib/npu` 同版本的 SDK headers、库清单和编译工具链。
- 对应 OM 的完整转换命令、AIPP 配置、输入输出 tensor 描述和类别文件。
- 一个支持内存图像输入的官方最小 C/C++ 示例，或稳定的共享库 C ABI。
- 在板端完成单图 golden test 后，再接入 `DetectorBackend -> tracker -> TrackState -> RiskModel`，不能绕过现有风险链路。

OpenVINO 仅用于 PC/通用 CPU 路径，不代表 SS928 NPU。
