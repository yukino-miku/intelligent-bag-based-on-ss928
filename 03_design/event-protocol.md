# 板端事件协议

视觉 detector stdout 只输出单行 JSON，普通日志全部写 stderr：

```json
{"type":"vision_alert","side":"left","level":2,"score":0.63,"track_id":120,"class":"car","distance_m":4.2,"ts":123.45}
```

`level` 必须来自稳定后的 `haptic_level`，不能使用 raw risk。`class` 和 `distance_m` 是向后兼容的可选字段。低于阈值不输出危险事件；已有风险下降或消失时立即输出对应 side 的 `level=0`。同侧同等级按 `--alert-rate-limit` 限流。固定侧 Controller 子进程会拒绝跨侧事件，并拒绝格式错误、未来时间异常、过旧和超出 0..4 的事件。

Controller 驱动 PWM 后通过统一 BLE TX 推送：

```json
{"typ":"alert","side":"left","level":2,"name":"CAUTION","score":0.63,"track_id":120,"class":"car","distance_m":4.2,"ts":123.45}
```

小程序分别维护左右当前状态；`level=0` 只清对应侧，历史条数有上限。视频经 Wi-Fi/LAN HTTP 传输，不进入 BLE NUS。

跌倒/撞击事件使用独立类型 `fall_confirmed`、`impact_only`、`possible_fall`，不得直接转换为交通震动等级。GNSS 和姿态数据也使用独立 `type`。
