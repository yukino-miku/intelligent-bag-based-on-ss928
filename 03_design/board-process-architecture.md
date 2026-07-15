# 板端进程架构

```text
vision detector
  -> stabilized haptic vision_alert JSONL
  -> smartbag alert controller
  -> PWM vibration / optional non-blocking audio

BMI270 -> posture + fall/impact board events -> controller/board service
DX-GP21 -> GNSS JSON -> local track store -> controller/board service
controller/board service -> one BLE NUS -> mobile mini program
```

默认单摄只启动一个 detector，并由目标地面 `x_m` 推断 left/right/both。双摄模式可显式提供左右 detector，但不作为默认配置。Controller 是默认 BLE 唯一所有者；GNSS/BMI 子模块通过 JSONL/stdin 呷令与它交互。

视觉风险层次必须保持：`raw_risk_level` 是单帧候选；`visual_risk_level` 是稳定后的画框级别；`haptic_risk_level` 是更严格的震动输入；实际 PWM 还会经过事件时效、侧别、限流和等级配置。
