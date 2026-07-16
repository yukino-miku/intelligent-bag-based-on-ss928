# 板端进程架构

```text
left USB camera -> left detector (single camera owner)
  -> left stabilized haptic vision_alert JSONL -> controller -> left PWM
  -> left raw/overlay latest frame -> detector-local HTTP

right USB camera -> right detector (single camera owner)
  -> right stabilized haptic vision_alert JSONL -> controller -> right PWM
  -> right raw/overlay latest frame -> detector-local HTTP

dual camera gateway -> proxy/aggregate both detector HTTP endpoints -> Wi-Fi/LAN -> phone

BMI270 -> posture + fall/impact board events -> controller/board service
DX-GP21 -> GNSS JSON -> local track store -> controller/board service
controller/board service -> one BLE NUS -> mobile mini program
```

正式部署默认启动两个固定 detector：左相机事件只能是 `left`，右相机事件只能是 `right`，中央目标也不跨侧发送。旧单摄 `--single-camera/--side auto` 只保留兼容测试，不进入默认 systemd 链。两个 detector 不共享 camera handle、tracker、TrackState、RiskModel、stabilizer、限流器或 risk CSV。

Controller 是默认 BLE 唯一所有者；GNSS/BMI 子模块通过 JSONL/stdin 命令与它交互。BLE 不传视频。`smartbag-video.service` 只代理 detector 已有的最新帧，不重新打开摄像头；手机无客户端时不会主动执行 JPEG 编码。

视觉风险层次必须保持：`raw_risk_level` 是单帧候选；`visual_risk_level` 是稳定后的画框级别；`haptic_risk_level` 是更严格的震动输入；实际 PWM 还会经过事件时效、侧别、限流和等级配置。
