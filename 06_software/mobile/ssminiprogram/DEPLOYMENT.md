# 微信小程序部署

## 1. 导入与 AppID

1. 在微信公众平台注册或选择一个小程序，取得 AppID。AppSecret 只保存在微信后台或受控密钥系统，不能写入本仓库。
2. 复制 `project.config.example.json` 为自己的 `project.config.json`，填写 `appid`。仓库中的 `touristappid` 仅用于无 AppID 的开发工具预览，不是可发布配置。
3. 在微信开发者工具选择“导入项目”，目录选择 `06_software/mobile/ssminiprogram`。
4. 检查小程序根目录为 `miniprogram/`，云函数根目录为 `cloudfunctions/`。

## 2. 仅局域网与 BLE

CloudBase 不是本地运行的前提。关闭 CloudBase 时仍可使用：

- BLE 连接统一设备名 `SS928-SmartBag`，读取当前风险、姿态和板端状态；
- 通过同一局域网访问板端 `/api/v1/status`、双摄快照、融合 overlay 和运行参数；
- 在手机本地保存最近的三级/四级交通事件元数据和图片；
- GNSS/BMI270 的本地 BLE 命令路由。

在“系统参数”或摄像头页填写板端实际 IP、端口和访问 token。IP 与 token 存在微信本地存储，不进入 Git。开发者工具可以临时关闭“校验合法域名”，真机和发布版必须按微信规则使用 HTTPS/WSS 合法域名；直接 HTTP 局域网只适合受控调试环境。

## 3. CloudBase 可选部署

1. 在微信开发者工具开通 CloudBase 环境，记录环境 ID，不要提交任何密钥。
2. 复制 `miniprogram/envList.example.js` 为本地 `miniprogram/envList.js`，填写 `envId`。
3. 为 `cloudfunctions/smartbag-device-ingest` 和 `cloudfunctions/smartbag-app-api` 分别安装依赖并上传部署。
4. 在云函数环境变量中设置 `CLOUDBASE_ENV_ID`。设备上传 token 应存于 CloudBase 密钥/环境变量，不写入函数源码。
5. 按 `docs/references/cloudbase-integration.md` 创建集合和权限，先用测试数据验证，再连接真实板端。

板端需要在 `/etc/smartbag/smartbag.env` 本地设置 CloudBase endpoint 和上传 token。安装包只提供空模板。

## 4. 实时参数与告警

- “系统参数”调用板端 `GET/PATCH /api/v1/settings/runtime`；界面显示的是板端返回的已生效值。
- “交通危险事件”只记录稳定后的融合/haptic 三级、四级事件，不使用 raw risk。
- 图片先从板端事件接口下载并保存到手机；CloudBase 启用后再异步上传。CloudBase 失败不影响板端震动和本地保存。
- 摄像头页通过 LAN/Wi-Fi 获取快照或 MJPEG，BLE 不承载视频。

## 5. 发布前检查

1. `project.config.json` 使用真实 AppID，且不包含 AppSecret。
2. `envList.js` 指向正确环境，测试环境和正式环境分开。
3. 合法域名、网络权限、隐私声明和用户授权符合微信平台要求。
4. 手机与板端实际网络可达，token 错误、板端离线、CloudBase 关闭均显示明确错误。
5. 运行 `for test in tests/*.test.js; do node "$test"; done`，再进行真机 BLE、局域网、三级/四级事件图片测试。
