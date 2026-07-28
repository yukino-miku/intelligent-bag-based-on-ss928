# 板端进程架构

完整架构和资源所有权以 [integrated-system-architecture.md](integrated-system-architecture.md) 为准。本文件保留部署入口摘要。

```text
left MR20  --+                              +--> left haptic --+
right MR20 --+--> radar tracks -> RiskModel +--> right haptic -+--> Controller
left/right USB -> one alternating detector -> current class map     | BLE/TM6605/lights/audio

BMI270 child -> posture/fall/reminder/cloud/SMS-call
DX-GP21 child -> valid GNSS track/cache/cloud
MT5710 service -> connectivity only
debug HTTP -> status/current snapshots/settings/alert history -> mini program
```

默认 `radar_primary_visual_classification` 使用双 MR20 连续跟踪和一个模型左右交替快照。Linux 原生 V4L2 预开两路资源，但任意时刻最多一侧 STREAMON；每张图片只更新本侧当前车型映射，风险以雷达位置/速度为准并按每轨迹 0.5 秒中位数窗口输出。`legacy_dual_vision` 才保留两个固定 detector、视觉 TrackState/RiskModel/stabilizer，用于 PC 回归和诊断，不属于默认板端启动链。

Controller 是 BLE、TM6605、灯、音频和 MR20 UDP worker 的唯一所有者；BMI/GNSS 默认 `--no-ble`。视觉风险层保持 `raw_risk_level -> visual_risk_level -> haptic_risk_level`，震动 JSONL 只允许稳定后的 haptic level。Controller 再按 source+side、事件时效和输出 profile 决定实际硬件等级。
