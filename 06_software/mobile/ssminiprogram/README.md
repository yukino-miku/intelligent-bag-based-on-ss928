# SS928 SmartBag 微信小程序

原生小程序包含首页、双摄画面、GNSS 轨迹、BMI270 姿态、monitor、tracks、BLE NUS、WGS84 到 GCJ-02 和本地告警历史。默认只扫描统一设备名 `SS928-SmartBag`。

CloudBase 是可选历史数据源，不替代 BLE。复制 `miniprogram/config/cloud.example.js` 为本地且被 Git 忽略的 `cloud.local.js`，填写自己的 EnvId/deviceId 后再启用。页面通过 `device-data-service` 统一读取，Cloud 超时或失败会回退 BLE，并显示来源与 stale 状态；双摄视频仍走板端局域网接口。

## 双摄实时画面

首页进入“**双摄实时画面**”后可配置：

- `boardHost`：板端 IP、主机名或含协议地址；不在代码中写死；
- `videoPort`：默认 8080；
- `accessToken`：可选；
- `refreshFps`：snapshot 刷新 1..10 FPS；
- 左右 API path、raw/overlay 模式。

配置保存在 `smartbagCameraConfig` (`wx.setStorageSync`)。页面同时显示左右 snapshot、在线状态、采集/推理/预览 FPS、最后帧延迟、风险、设备路径和更新时间，并支持暂停、恢复、重连和单侧大图。当前启用 `SnapshotHttpTransport`；`CameraTransport` 保留后续协议扩展边界。MJPEG endpoint 供浏览器验证，不宣称已在微信 `<image>` 中稳定连续播放。

## 自动告警

Controller 通过 BLE TX 推送 `typ=alert`。monitor 分别维护左右当前状态，并把最多 100 条历史保存到本地 `wx.setStorageSync`；重启或 BLE 暂时断开后仍可查看。记录包括左右方向、中文等级、effective/haptic level、light mode、audio clip/enabled、source/source ID、track/class/distance/TTC/score、source/receive 时间和 BLE/Cloud 来源。有 `clear_reason` 的 0 级解除事件会显示“左/右侧预警已解除”；heartbeat、非 alert JSON 和两秒内完全重复事件不进入历史。手动清除会同步删除本地历史。

命令命名空间：

```text
AL L1 / AL R2 / AL CLEAR
GNSS TL / GNSS TG <i> <offset> / GNSS TF 1 / GNSS TS
IMU STATUS / IMU ZERO / IMU ZERO_V / IMU SET <key>=<value>
SYS STATUS
```

## 导入和真机限制

用微信开发者工具导入本目录。仓库的游客 AppID 只用于工具预览；真机 BLE 和局域网必须换成自己的小程序配置。开发调试可临时勾选“不校验合法域名、TLS 版本及 HTTPS 证书”，但正式环境必须按微信当前网络规则配置 AppID、通信域名/HTTPS，并在目标 iOS、Android 微信版本上验证。

官方网络规则说明局域网 IP 从基础库 2.4.0 起可用于网络接口，但手机和板端仍必须互相可达，且 AP 客户端隔离、系统网络权限、基础库版本和发布配置都可能影响结果：<https://developers.weixin.qq.com/miniprogram/dev/framework/ability/network.html>。

未完成真实手机验证时，先用浏览器打开 `http://<BOARD_IP>:8080/`，再验证小程序 snapshot。不要把开发者工具成功写成正式真机已完成。

## 工具测试

```sh
node tests/alarm-utils.test.js
node tests/track-utils.test.js
node tests/camera-transport.test.js
node tests/alert-state.test.js
node tests/cloud-security.test.js
node tests/device-data-service.test.js
```

云函数源码在 `cloudfunctions/smartbag-api`。部署前创建 `device_bindings` 等集合、配置 nonce TTL 和 `SMARTBAG_DEVICE_SECRETS_JSON` 环境变量；不能把 OPENID、EnvId、HMAC secret、管理员密钥或固定 `deviceId` 写入仓库。当前仓库只完成源码与 mock 测试，不表示已部署 CloudBase。
