# Rev2 Autonomous Runtime - Latest Summary

- branch: `agent/rev2-autonomous-board-runtime`
- baseline: `agent/sanda-hardware-refresh@0fbe815e8a7f51fc32e925bce086be99ceca84a9`
- local code: `TESTED`
- board code staging: `TESTED`
- production install/systemd enable: `NOT RUN`
- camera-only board test: `PARTIAL PASS`
- physical haptics/lights/audio/GNSS/IMU/MR20/BLE: `NOT RUN`
- power-only reboot 1/2: `NOT RUN`
- final acceptance: `POWER_ONLY_AUTOSTART_NOT_READY`

## 2026-07-20 板端暂存

- 通过 USB-UART 将提交 `a660901` 的 315 个文件暂存到
  `/root/smartbag-staging/a660901/repo`，压缩包两端 SHA-256 均为
  `512662B1E9B9551ED83B6AE1E224C39ECFF3C4A91A19F70E77C58461C7AE7044`。
- 没有执行 `install.sh`，没有写入生产 `/root/smartbag`，没有 enable
  `smartbag.target`，也没有驱动执行器。板上原有 BMI/alert 服务只在摄像头
  隔离测试期间停止，未修改 enable 状态。

## 双摄交替采集

测试时两台 UVC 位于 USB 路径 `3-1.3` 和 `3-1.4`，采集主节点为
`/dev/video0`、`/dev/video2`。重启后两个设备号发生互换，因此左右配置必须
使用稳定物理路径或显式身份映射，不能永久绑定数字节点。

请求 `1680x1050 MJPEG @10 FPS` 的 10 次交替测试结果：

| 项目 | 实测 |
|---|---:|
| session 时长 | 5.355 s |
| 切换 | 10/10，100% |
| 左/右有效帧 | 20/20 |
| STREAMON/OFF、首帧超时、重连、丢帧、USB 错误 | 0 |
| 每侧有效 FPS | 3.735 |
| 切换 p50/p95 | 264.301/293.734 ms |
| 首帧 p50/p95 | 60.458/94.464 ms |
| 最大 capture-only 盲区 | 545.945 ms |

驱动实际输出的两张 JPEG 均为 `1920x1080`，不是请求的 `1680x1050`；右路
物理安装方向旋转 90 度。两张原图已用串口回传并通过 SHA-256 校验，现场图
只保存在 Git 忽略的 `08_media`，不上传 GitHub。该测试是单路轮流 STREAMON
的交替采集，不是双路同时采集或同步处理。

## SS928 NPU 快照推理

- 使用板上 `/opt/sample/yolov8/yolov8n.om` 和 `/opt/lib/npu/libascendcl.so`
  对左右快照各执行一次推理；输入为 `1x640x640x3 uint8`，输出为
  `1x84x8400 float`，两侧 `.bin` 和后处理 `.txt` 均生成。
- 干净启动后的模型执行时间为 `25.44 ms`，示例报告 `39.31 FPS`；包含 JPEG
  解码和后处理的两图总耗时约 `1.14 s`，不能把纯 NPU FPS 当成完整视觉 FPS。
- 现场画面只有天花板和瓶子，没有 car/bicycle/motorcycle/bus/truck；左右
  最大候选置信度分别为 `0.0450` 和 `0.0342`，`conf>=0.25` 无目标。因此只
  证明 USB 快照可以进入 NPU 并产生输出，不证明真实交通目标检测命中。
- 通用 ModelZoo harness 原资源销毁顺序不适配当前板端 ACL。临时构建已将
  `aclmdlUnload()` 调整到描述符/数据集销毁之前并返回 0，但随后
  `EnvDeinit()` 仍触发 `munmap_chunk(): invalid pointer`，进程退出码 134。
  该临时第三方构建位于 `08_media` 且不提交；正式 `Ss928OmBackend` 仍是
  BLOCKED，不能宣称连续实时识别链已经可用。

## 本地验证

- Python：共运行 `280` 项，`279` 项通过、`1` 项 Linux-only `fcntl`
  跨进程锁测试在 Windows 跳过；新增 4 项串口传输 helper 测试均通过。
- 小程序：`6` 个 JavaScript 测试文件通过；`24` 个 JavaScript 文件通过
  `node --check`。
- Python `compileall`、`22` 个受控 JSON、`38` 个 shell `sh -n`、Rev2
  `safe_off.py --dry-run --strict` 和硬件刷新仓库策略均通过。

结论：双 UVC 交替采集和两张快照进入 SS928 NPU 已验证；真实目标命中、
持续 NPU 运行、BoT-SORT、风险链、overlay、执行器、完整部署、自启动和
脱离电脑运行仍未通过。`PARTIAL PASS` 不等于生产部署完成。

`POWER_ONLY_AUTOSTART_NOT_READY`
