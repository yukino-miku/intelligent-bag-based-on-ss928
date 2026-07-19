# 交替双摄最新验证摘要

日期：2026-07-19
基线：`06c6cfd1dc11a0f92c54ce8aad5252d554ececa5`
分支：`agent/alternating-dual-camera`

## 已验证

- SS928 板端原生 V4L2 mmap + `VIDIOC_STREAMON/OFF`。
- A1-A4 每组 2 分钟，总计 989 次切换，成功率 100%，无 ENOSPC、无首帧超时。
- 实际协商均为 MJPEG 30 FPS；5/10 FPS 只是请求值。
- p95 切换延迟范围 273.726-278.018 ms。
- 最大单侧盲区范围 509.928-539.016 ms。
- 640x480 左右有效 FPS 约 4.08-4.13；320x240 约 4.10-4.13。
- RSS 峰值：640x480 约 27.4 MiB，320x240 约 23.4 MiB。
- B 阶段状态、左右快照和调试页均 HTTP 200，未激活侧标记为缓存帧。
- 额外请求 1680x1050@10 的 30 秒测试被实际协商为 1920x1080@30；61/61 次切换成功、无 ENOSPC，p95 278.613 ms、最大盲区 509.999 ms、RSS 峰值 54.836 MiB。
- 退出后两路设备均无占用。
- PC 端真实 YOLO 模型只加载一次，左右 BoT-SORT 实例和历史独立。
- C 入口按片采集完成后立即 STREAMOFF，再执行 decode/inference/tracking/risk；阶段耗时分别写入 CSV。
- D 自动测试确认 heartbeat 不进入 BLE 历史、未观测侧不被当成 SAFE、stale/detector exit 会清振。
- 本地 224 项 Python 测试、4 个小程序测试文件和真实 Ultralytics 单模型/双 tracker 冒烟通过；板端交替采集 12 项、controller 9 项、compileall、shell 语法和 JSON 解析通过。

## 尚未验证

- 未完成 30 分钟连续 A 阶段验收。
- 板端缺少 OpenCV、torch、Ultralytics、lap，C 阶段板端推理未运行。
- D 阶段 PWM/BLE 只有单元和集成测试，未驱动真实电机。
- 板端温度节点未找到，温度指标为空。

结论：A/B 可行，但尚不满足默认启用 `alternating_single_model` 的条件；正式默认仍为 `fixed_dual_process`。
