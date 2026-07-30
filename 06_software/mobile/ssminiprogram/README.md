# SS928 SmartBag 微信小程序

原生小程序包含：首页、左右摄像头画面、雷视 monitor、交通危险事件、运行参数、GNSS tracks、BMI270 姿态、云端姿态分析/实时状态、跌倒告警历史和统一 BLE remote。默认设备名为 `SS928-SmartBag`。

## 导入

用微信开发者工具导入本目录。`miniprogram/envList.js` 默认不写 CloudBase 环境；在自己的项目中配置合法 env/AppID。两套函数分别位于：

完整的 AppID、局域网/BLE、CloudBase、云函数和发布步骤见 [DEPLOYMENT.md](DEPLOYMENT.md)。仓库同时提供 `project.config.example.json` 和 `miniprogram/envList.example.js` 空模板。

- `cloudfunctions/smartbag-device-ingest`：HTTP telemetry ingest，需要服务端 `CLOUDBASE_ENV_ID` 和上传 token。
- `cloudfunctions/smartbag-app-api`：小程序读取 status、posture、track 和 alarm，并可异步保存已确认的三级/四级交通事件元数据。

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

## 参数与交通事件

“系统参数”页复用 `smartbagCameraConfig` 中的 `boardHost`、`videoPort` 和 `accessToken`，访问：

```text
GET   /api/v1/settings/runtime
PATCH /api/v1/settings/runtime
POST  /api/v1/settings/runtime/reset
```

页面只提交板端白名单参数，成功后显示实际生效值和配置版本。IP 不写死；板端离线或参数校验失败会显示错误，不覆盖当前表单为假成功。

BLE 收到 level 3/4 且包含 `event_id` 时，小程序先按 event_id 保存本地元数据，再请求板端事件详情和同侧 JPEG，使用 `wx.saveFile` 保存。网络失败标记 `retry_pending`，可在“交通危险事件”页重试；历史默认保留 80 条和 30 张本地图片，旧图片会清理。CloudBase 已启用时异步上传事件/图片，失败不会影响板端保存、BLE 当前状态或手机本地历史。

## 测试

```sh
for test in tests/*.test.js; do node "$test"; done
```

测试覆盖告警状态、交通事件去重/离线降级/图片清理、参数/页面路由、双摄 transport、首页、姿态、CloudBase contract、remote 和轨迹工具。开发者工具预览通过不等于手机真机/发布版已验收。
