# SS928 MPP 与模型部署边界

## MPP

IMX347 preview 依赖厂商 MPP Sample 的 `src/Makefile.param`、MPI/AUDIO/iniparser 库和 sensor 驱动。仓库 Makefile 使用可覆盖变量：

```sh
make MPP_SAMPLE_ROOT=/opt/ss928/mpp/sample
```

不要把 SDK、固件镜像或 MPP 二进制提交到公共仓库。VI/VPSS/VO 跑通只证明视频链路可用，不代表 YOLO 已使用 NPU。

## 模型后端

PC 端继续使用 `UltralyticsBackend` 和 PyTorch/OpenVINO。板端已实现 `Ss928OmBackend`：常驻加载 `.om`，通过 ACL 内存输入执行 NPU 推理，完成 RGB planar letterbox、COCO 类别过滤、NMS、坐标恢复和轻量 tracker，再复用原风险与 overlay 链。OpenVINO 不是 SS928 NPU。

当前模型契约固定为 RGB_PLANAR 输入和单个 FP32 `1x84x8400` 输出。仍需在真实板上完成连续双摄目标命中、PyTorch 基线对齐、FPS/CPU/NPU/端到端时延/温度和 30 分钟稳定性验收。MPP/VPSS 零拷贝属于后续优化；当前正式链路使用一次受控 CPU 内存预处理和 ACL 缓冲区拷贝，不伪称零拷贝。
