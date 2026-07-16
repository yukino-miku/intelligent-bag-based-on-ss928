# SS928 MPP 与模型部署边界

## MPP

IMX347 preview 依赖厂商 MPP Sample 的 `src/Makefile.param`、MPI/AUDIO/iniparser 库和 sensor 驱动。仓库 Makefile 使用可覆盖变量：

```sh
make MPP_SAMPLE_ROOT=/opt/ss928/mpp/sample
```

不要把 SDK、固件镜像或 MPP 二进制提交到公共仓库。VI/VPSS/VO 跑通只证明视频链路可用，不代表 YOLO 已使用 NPU。

## 模型后端

当前完整可用后端是 `UltralyticsBackend`，PC 可使用 PyTorch/OpenVINO，板端 `board_cpu` 只是一套低负载参数。OpenVINO 不是 SS928 NPU。`Ss928OmBackend` 目前只定义接口并给出明确未实现错误，不伪造推理结果。

后续 `.om` 工作需要：确定官方 ModelZoo/转换工具版本；固定输入尺寸、颜色空间、量化和 NMS 契约；实现 MPP/VPSS 零拷贝或受控拷贝；映射 detector 输出到现有 `Observation`；以录制视频对齐 PyTorch 基线；最后在真实板上测量 FPS、CPU/NPU 占用、端到端时延和温度。
