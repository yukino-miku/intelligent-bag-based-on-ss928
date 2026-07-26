# SS928 SmartBag 微信小程序

原生小程序包含：首页、左右摄像头画面、monitor、GNSS tracks、BMI270 姿态、云端姿态分析/实时状态、跌倒告警历史和统一 BLE remote。默认设备名为 `SS928-SmartBag`。

## 导入

用微信开发者工具导入本目录。`miniprogram/envList.js` 默认不写 CloudBase 环境；在自己的项目中配置合法 env/AppID。两套函数分别位于：

- `cloudfunctions/smartbag-device-ingest`：HTTP telemetry ingest，需要服务端 `CLOUDBASE_ENV_ID` 和上传 token。
- `cloudfunctions/smartbag-app-api`：小程序读取 status、posture、track 和 alarm。

quickstartFunctions、example、默认脚手架素材和 private config 已移除。Cloud token、设备 IP 和访问 token 不写入仓库。

## 双摄画面

摄像头页保存 `boardHost`、gateway port、可选 token、refresh FPS 和 raw/overlay 选项。Gateway 只通过 LAN/Wi-Fi 提供 snapshot/MJPEG；BLE 不传视频。开发工具可临时关闭域名校验，正式真机仍需实际 AppID、网络权限、HTTPS/合法域名和手机到板端的可达性。

## BLE 命令

使用 Nordic UART Service UUID `6E400001/2/3`，默认只连接统一设备：

```text
AL L1 / AL R2 / AL CLEAR
GNSS TL / GNSS TG <i> <offset> / GNSS TF 1 / GNSS TS
IMU STATUS / IMU ZERO / IMU ZERO_V / IMU SET <key>=<value>
SYS STATUS
```

视觉/雷达告警按 side 独立显示；`level=0` 只清对应侧。CloudBase 加载失败显示不可用状态，不制造设备在线、电量或位置。

## 测试

```sh
for test in tests/*.test.js; do node "$test"; done
```

测试覆盖告警状态、历史页、双摄 transport、首页、姿态、CloudBase contract、remote 和轨迹工具。开发者工具预览通过不等于手机真机/发布版已验收。
