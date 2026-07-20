# CloudBase 集成状态

## 已实现源码

- 板端 `cloud_uploader`：读取 controller/GNSS/IMU 状态和告警 JSONL，使用有界离线队列、持久 cursor、指数退避、HTTPS、HMAC-SHA256、timestamp、nonce、body SHA256 和请求超时。
- 云函数 `smartbag-api`：设备上传签名和 payload 限制、nonce 唯一文档、`device_bindings` 授权查询、`cloud.getWXContext()` 身份、轨迹/告警 cursor 分页。
- 小程序：`cloud.local.js` 本地配置、BLE/Cloud 统一数据源、Cloud 失败回退 BLE、来源和 stale 状态；视频仍走局域网 snapshot/MJPEG。

## 部署边界

仓库示例默认 `enabled=false`，EnvId、deviceId、AppID、URL 和 HMAC secret 均为空或占位。真实 secret 只能存放在板端受保护的 `EnvironmentFile` 和 CloudBase 环境变量 `SMARTBAG_DEVICE_SECRETS_JSON`。客户端传入的 OPENID 不被信任。

当前为 `IMPLEMENTED + UNIT TESTED`，不是 `CLOUD DEPLOYED`。真实环境需要建立 `devices`、`device_bindings`、`device_status`、`track_points`、`alarm_history`、`posture_daily_stats`、`device_nonces`，为 nonce 集合配置 TTL，并完成用户绑定、错误签名、重放、未授权、分页和断云不影响 BLE 的验收。
