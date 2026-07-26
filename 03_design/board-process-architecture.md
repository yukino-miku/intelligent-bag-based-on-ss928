# 板端进程架构

完整架构和资源所有权以 [integrated-system-architecture.md](integrated-system-architecture.md) 为准。本文件保留部署入口摘要。

```text
left fixed USB camera  -> left detector  -> haptic JSONL --+
right fixed USB camera -> right detector -> haptic JSONL --+--> Controller
optional MR20 workers -------------------------------------+      | BLE/TM6605/lights/audio

BMI270 child -> posture/fall/reminder/cloud/SMS-call
DX-GP21 child -> valid GNSS track/cache/cloud
MT5710 service -> connectivity only
video gateway -> detector latest frames only -> LAN/mini program
```

正式部署始终使用两个固定 detector，不使用交替采集。每个 detector 独占对应 camera、tracker、TrackState、RiskModel、stabilizer、限流和 risk CSV。Gateway 不重新打开 camera。

Controller 是 BLE、TM6605、灯、音频和 MR20 UDP worker 的唯一所有者；BMI/GNSS 默认 `--no-ble`。视觉风险层保持 `raw_risk_level -> visual_risk_level -> haptic_risk_level`，震动 JSONL 只允许稳定后的 haptic level。Controller 再按 source+side、事件时效和输出 profile 决定实际硬件等级。
