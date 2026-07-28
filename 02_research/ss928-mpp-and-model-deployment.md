# SS928 MPP 与模型部署边界

## MPP

IMX347 preview 依赖厂商 MPP Sample 的 `src/Makefile.param`、MPI/AUDIO/iniparser 库和 sensor 驱动。仓库 Makefile 使用可覆盖变量：

```sh
make MPP_SAMPLE_ROOT=/opt/ss928/mpp/sample
```

不要把 SDK、固件镜像或 MPP 二进制提交到公共仓库。VI/VPSS/VO 跑通只证明视频链路可用，不代表 YOLO 已使用 NPU。

## 模型后端

PC 完整后端是 `UltralyticsBackend`，可使用 PyTorch/OpenVINO；`board_cpu` 只是一套低负载参数，OpenVINO 不是 SS928 NPU。板端 `Ss928OmBackend` 已接入持久 native runner：模型只初始化一次，Python 将交替获取的最新 BGR 快照 letterbox 到固定 640x640、转换为 NV12，并通过 stdin/stdout 单行协议请求 OM 检测。runner 超时或退出时重启并只重试一次，失败帧明确返回 `MODEL_ERROR`，不会伪造检测框。

该桥接仅为“车辆类别快照分类”服务，不承担视觉测距、测速、跟踪或风险判断。正式融合模式由 MR20 连续提供运动数据，OM 结果只绑定 `bicycle/motorcycle/car/truck/bus` 类别；无视觉结果时仍以 `unknown=1.0` 运行共享 RiskModel。

尚未验收的 `.om` 工作包括：取得许可明确且输出契约匹配的车辆模型；在真实板上验证类别、框坐标和置信度；校验 ModelZoo/转换工具、量化和 NMS 契约；评估 MPP/VPSS 零拷贝；最后测量每侧快照频率、切换时延、CPU/NPU 占用、RSS、温度和 30 分钟稳定性。仓库中的工厂 OM 历史证据未产生可信目标，不能作为模型正确性证明。
