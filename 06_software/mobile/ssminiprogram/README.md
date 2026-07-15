# SS928 SmartBag 微信小程序

原生小程序保留首页、GNSS 轨迹、BMI270 姿态、monitor、tracks、BLE NUS 工具、WGS84 到 GCJ-02、alarm-utils 和 track-utils。已移除 example、placeholder、quickstart cloudfunction、默认脚手架图片和 private config。

默认只扫描统一设备名 `SS928-SmartBag`，不再同时要求 `DX-GP21-Track` 与 `BMI270-Backpack` 两个 NUS。命令使用：

```text
AL L1 / AL R2 / AL CLEAR
GNSS TL / GNSS TG <i> <offset> / GNSS TF 1 / GNSS TS
IMU STATUS / IMU ZERO / IMU ZERO_V / IMU SET <key>=<value>
SYS STATUS
```

用微信开发者工具导入本目录，`project.config.json` 使用游客 appid；真机测试前替换为自己的小程序配置。BLE 权限、定位权限和 Nordic UART 链路必须用手机验证，模拟器不能替代真实 BLE。

工具测试：

```sh
node tests/alarm-utils.test.js
node tests/track-utils.test.js
```
