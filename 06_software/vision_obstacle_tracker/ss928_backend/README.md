# SS928 OM 检测后端（实验性）

本目录把来源仓库中可复用的 SS928 AscendCL/OM 模型描述、NV12 预处理和 YOLO 输出解码能力，收敛为目标仓库的“检测结果生产者”。它不会替换 `vision_obstacle_tracker.py` 的跟踪、单目测距、Future Conflict Gate、多帧稳定、visual/haptic 分层和自身前景过滤。

## 当前验收边界

来源提交 `59071297e5d8f339332a7234406429f94ffe2570` 的实板证据表明：固定输入的 1 帧/100 帧 ACL 执行成功，100 帧平均推理约 25.112 ms、后处理约 16.292 ms、整体约 23.348 FPS。但工厂 `yolov8n.om` 对两张已知图像没有产生有效目标候选，类别最大值也异常偏低。因此：

- 已具备：模型 I/O 合约校验、NV12 letterbox、YOLO 解码/NMS、目标类别过滤、离线 raw-NV12 runner、单行 detections JSONL。
- 未验收：工厂 OM 的真实检测正确性、双 USB 实时采集、检测 JSONL 到 Python tracker/risk 的实时桥接、长时间双路 NPU 性能。
- 不得声称“USB -> SS928 NPU -> 跟踪/风险 -> overlay”已完成，也不得用 OpenVINO 冒充 SS928 NPU。

详细失败证据见 [diagnostics/STAGE_G_EVIDENCE.md](diagnostics/STAGE_G_EVIDENCE.md)。模型和输出二进制不进入 Git。

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

## 离线板端运行

将合法来源的 `.om` 放到 `/root/smartbag/models/yolov8n.om`，并准备与模型尺寸一致的 NV12 文件：

```sh
cd /root/smartbag/vision/ss928_backend
./scripts/run_offline.sh /path/frame.nv12 100 \
  > /tmp/detections.jsonl \
  2> /tmp/detection-runner.log
```

stdout 只输出单行 `type=detections` JSON；模型信息和诊断进入 stderr。输出协议由 `detection_protocol.py` 解析并有 Python 单元测试。

## 正式接入待办

1. 使用与模型转换配置匹配的已验证 OM，通过真实目标图像验收类别、坐标和置信度。
2. 为固定左/右 USB 设备分别提供无积压的最新帧 NV12 输入，不恢复交替采集。
3. 把 detections JSONL 接入现有 Python `TrackState`/`RiskModel`，确保震动只使用稳定后的 `haptic_level`。
4. 实板验证双路 FPS、内存、温度、退出清零和 systemd 重启行为。
