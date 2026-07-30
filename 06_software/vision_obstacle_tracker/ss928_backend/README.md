# SS928 OM 检测后端（实验性）

本目录把 SS928 AscendCL/OM 模型描述、descriptor 驱动预处理和 YOLO 输出解码能力收敛为“检测结果生产者”。PC 纯视觉回归仍使用 `vision_obstacle_tracker.py` 的完整链；正式雷达主导模式则只用本后端识别交替快照中的车辆类别，运动和风险数据来自 MR20。

## 当前验收边界

来源提交 `59071297e5d8f339332a7234406429f94ffe2570` 的实板证据表明：固定输入的 1 帧/100 帧 ACL 执行成功，100 帧平均推理约 25.112 ms、后处理约 16.292 ms、整体约 23.348 FPS。但工厂 `yolov8n.om` 对两张已知图像没有产生有效目标候选，类别最大值也异常偏低。因此：

- 已具备：模型 I/O 合约校验、固定 640x640 letterbox、NV12 UINT8/RGB_PLANAR UINT8/RGB_PLANAR FP32 descriptor 自动选择、YOLO 解码/NMS、目标类别过滤、持久 stdin 服务模式、单行 detections JSONL，以及 Python BGR24 快照桥接和超时重启。
- 已接入：`radar_vision_fusion` 共享一个 `Ss928OmBackend`，左右相机交替请求同一 runner；检测结果只用于雷达轨迹车型绑定，不创建视觉 tracker。
- 已构建：`09_deliverables/board_deploy/bin/aarch64` 中的 runner 和 `om_inspect` 是 stripped AArch64 ELF，只动态依赖板端 `libascendcl.so` 与 glibc；哈希见同目录 manifest。
- 未验收：候选 OM 的板端 descriptor/车辆检测正确性、真实双 USB 切换频率、雷达-相机标定/关联正确性和长时间 NPU 性能。
- 不得声称正式板端链已通过硬件验收，也不得用 OpenVINO 冒充 SS928 NPU。

详细旧模型失败证据见 [diagnostics/STAGE_G_EVIDENCE.md](diagnostics/STAGE_G_EVIDENCE.md)。合法模型不在仓库；项目源码构建的 runner 二进制进入 Git，厂商 ACL runtime/SDK 不进入 Git。

## 本机单元测试

需要支持 C++14 的 `g++`：

```sh
cd 06_software/vision_obstacle_tracker/ss928_backend
make native-tests
```

这些测试不链接板端 ACL 库，覆盖模型描述、预处理、解码和 ACL 合约。

## 交叉编译

```sh
cd 06_software/vision_obstacle_tracker/ss928_backend
make clean
make all \
  CROSS_COMPILE=/opt/linux/x86-arm/aarch64-mix210-linux/bin/aarch64-mix210-linux- \
  SDK_ROOT=/opt/ss928-sdk/mpp_sample
```

`SDK_ROOT`、交叉工具链和 stub 库必须与实际板端镜像匹配；仓库不携带完整 SDK。

也可以使用版本化的 Zig 构建脚本：

```sh
SDK_ROOT=/opt/ss928-sdk/mpp_sample ZIG=zig \
  ./scripts/build_aarch64_release.sh
```

## 离线板端运行

将合法来源的 `.om` 放到 `/root/smartbag/models/vehicle-detector.om`。`Ss928OmBackend` 会把 BGR24 帧交给 runner，runner 根据实际 ACL descriptor 选择输入格式；离线 exact-model-buffer 模式仍可用于底层诊断。

```sh
cd /root/smartbag/vision/ss928_backend
./bin/ss928_detection_runner --model /root/smartbag/models/vehicle-detector.om \
  --input /path/frame.bgr --input-format bgr24 --source-width 640 --source-height 480 \
  > /tmp/detections.jsonl \
  2> /tmp/detection-runner.log
```

stdout 只输出单行 `type=detections` JSON；模型信息和诊断进入 stderr。输出协议由 `detection_protocol.py` 解析并有 Python 单元测试。

## 雷达融合接入与待办

1. 使用与模型转换配置匹配的已验证 OM，通过真实目标图像验收类别、坐标和置信度。
2. 在当前 UVC by-path 上验证任意时刻最多一路 STREAMON、无积压最新帧和失败后下一侧继续运行。
3. 使用真实左右外参验证雷达投影、一一关联和车型持久绑定；风险始终由共享 RiskModel 处理雷达运动数据。
4. 实板验证每侧快照频率、NPU/CPU、RSS、温度、退出清零、systemd 重启和 30 分钟稳定性。
