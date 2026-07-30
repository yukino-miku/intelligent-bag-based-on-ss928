# SS928 板端部署说明

## 1. 正式架构与安全降级

默认 full 模式是 `radar_primary_visual_classification`：双 MR20 持续采集，左右 UVC 只交替 STREAMON，共用一个 `vehicle-detector.om`。视觉只决定车辆类别，距离和速度始终来自雷达。`radar_only` 只关闭 classifier，仍启动 `RadarVisionFusionRuntime -> RadarTrackManager -> 共享 RiskModel -> 0.5 秒中位数 -> Controller`。

摄像头、runner 或模型异常时类别退化为 `unknown`；雷达 worker 异常会自动清零该侧输出并指数退避重启。旧 `RadarRiskEvaluator` 只允许显式 `legacy_mr20_threshold_test`。

## 2. 一键安装

```sh
git clone https://github.com/yukino-miku/intelligent-bag-based-on-ss928.git
cd intelligent-bag-based-on-ss928
sudo ./install-on-ss928.sh --interactive
sudo reboot
```

常用参数：

| 参数 | 作用 |
|---|---|
| `--interactive` | 交互发现左右相机并引导标定；标定不完整时保持 radar-only |
| `--full` | 要求当前相机身份绑定的左右实测标定，启用 OM 分类 |
| `--radar-only` | 关闭视觉分类，但不改变共享风险核心 |
| `--yes` | 非交互；只允许复用已经验证的 hardware-discovery |
| `--profile PATH` | 选择硬件 profile |
| `--model-source PATH` | 使用另一个通过 manifest 的 OM |
| `--runner-source PATH` | 使用另一个通过 manifest 的 AArch64 runner |
| `--offline` | 不调用 apt/network，依赖必须已经存在 |
| `--skip-optional` | 跳过可选依赖 |
| `--no-start` | 安装并 enable，不立即启动 |
| `--reset-hardware-discovery` | 丢弃旧相机身份并重新确认 |
| `--reset-calibration` | 丢弃旧融合标定并回到模板 |

安装器检查 root、AArch64、内存/磁盘、ACL、OM/runner SHA 与契约，复制到统一 `/root/smartbag`，生成 32 字节以上管理/只读 Token，保留 `/etc/smartbag` 和 `/var/lib/smartbag`，安装 systemd，执行 preflight，并在失败、信号或异常时 safe-off。重复运行是升级，不清除配置和事件。

## 3. 首次相机分配

```sh
sudo ./camera-discover.sh
sudo ./camera-assign.sh --interactive
cat /etc/smartbag/hardware-discovery.json
ls -l /dev/smartbag-camera-left /dev/smartbag-camera-right
```

发现器按物理 `ID_PATH + serial + index0` 去重；没有 `/dev/v4l/by-path` 时才回退 `/dev/video*`。交互流程分别单路抓图，不同时 STREAMON，并要求用户确认候选 A 是左侧还是右侧。保存后安装 udev 规则。摄像头换 USB 口或身份变化后必须重新验证，历史拓扑不会自动套用。

`--yes` 不会猜左右，只能使用已存在且连续单路抓图验证通过的 discovery 文件。

## 4. MR20 网络和健康检查

编辑 `/etc/smartbag/mr20.json`，确认两台雷达 IP、UDP port、side、坐标方向、安装偏移和 yaw。配置静态网卡前先预览：

```sh
sudo ./mr20-network-setup.sh --interface eth0 --address 192.168.1.168/24 --dry-run
sudo ./mr20-network-setup.sh --interface eth0 --address 192.168.1.168/24 --apply
sudo python3 ./mr20-live-check.py --config /etc/smartbag/mr20.json --duration 10
```

网络脚本在修改前备份地址、路由和 netplan。live check 要求路由存在、ping 或邻居表可达、UDP 可绑定、收到合法 14 字节 0x60A/0x60B，并在期限内组出完整扫描或合法零目标扫描。运行状态还显示完整率、最新扫描年龄、sequence gap、orphan、worker 存活、错误和重启次数。

## 5. 融合标定

full 模式不接受 `UNMEASURED_TEMPLATE`。先完成相机分配，再运行：

```sh
sudo ./smartbag-calibrate-fusion.sh --interactive
sudo ./install-on-ss928.sh --full --yes
```

向导逐侧收集至少 4 个已知雷达位置与图像像素，输入相机/雷达安装高度、横向位置和 pitch，拟合水平投影并记录 `sample_count`、`horizontal_rmse_px`、`max_error_px`、时间、`hardware_id`、`camera_by_path`、`radar_name`。验证器要求误差达标且标定身份与当前 discovery 一致。

完整外参优先于简化安装参数。若内参有固定 `camera_fx`，FOV 是只读推导值；API 会返回 requested/effective/source/editable，小程序不会让用户保存实际不生效的参数。

## 6. API 与 Token

首次安装在 `/etc/smartbag/smartbag.env` 生成：

```text
SMARTBAG_API_TOKEN=<管理Token>
SMARTBAG_API_READONLY_TOKEN=<只读Token>
```

文件必须 `root:root 0600`。默认绑定 `127.0.0.1`；监听非 loopback 时至少必须配置 Token。GET 状态、目标、事件和图片接受管理或只读 Token；PATCH/reset 只接受管理 Token。Token 通过 `Authorization: Bearer` 或 `X-SmartBag-Token` 传递，不使用 URL query，也不写日志。

```sh
. /etc/smartbag/smartbag.env
curl -H "Authorization: Bearer $SMARTBAG_API_READONLY_TOKEN" \
  http://127.0.0.1:8080/api/v1/fusion/status
curl -H "Authorization: Bearer $SMARTBAG_API_TOKEN" \
  http://127.0.0.1:8080/api/v1/settings/runtime
```

## 7. 风险、图片与保留策略

- 每目标窗口默认 0.5 秒，至少 3 个样本、0.25 秒观测、足够完整率和雷达质量，才允许正式 L3/L4。
- 极近 fast path 仍要求至少 2 个有效样本、有效 closing speed、完整扫描、路径冲突和高质量。
- 视觉事件记录 `frame_id/timestamp/detection_id/radar_track_key/association_score`；原帧不存在时保存无错误高亮的 `frame_mismatch` 图片。
- 默认保留 500 个事件、200 张图片、256 MiB、30 天；先删最旧非活动图片，再清理非活动事件，原子压缩 JSONL。升级和默认卸载保留历史。

## 8. 启动、状态与验收

```sh
sudo systemctl enable --now smartbag.target
systemctl status smartbag.target
journalctl -u smartbag-alert.service -f
sudo ./status.sh --check
sudo ./validate-on-ss928.sh --full --duration 30m
```

`validate-on-ss928.sh` 记录静态预检、runner 版本、服务/API 连续健康证据。它不能替代 reboot 和独立供电测试；完成后仍需：

```sh
sudo reboot
# 重连后检查 smartbag.target，再拔除电脑并独立供电冷启动复查。
```

## 9. 小程序

导入 `06_software/mobile/ssminiprogram`。板端 IP 与 Token 保存在微信本地设置，不进入 Git；CloudBase 不是本地 BLE、状态、风险、参数和事件图片功能的前提。正式 AppID/AppSecret/CloudBase 密钥必须自行配置，`touristappid` 只用于开发工具示例。详见小程序 [DEPLOYMENT](../../06_software/mobile/ssminiprogram/DEPLOYMENT.md)。

## 10. 许可和已知限制

正式 OM 和 runner 已进入 Git 与 RC2；静态 SHA/架构/I/O 契约可验证，真实 SS928 ACL 加载、同图 OM 对齐和 30 分钟实测仍是 `PENDING`。SS928 SDK、`libascendcl.so`、板端驱动和系统镜像必须来自匹配厂商镜像，不随仓库分发。

停止和卸载：

```sh
sudo ./stop-all.sh
sudo ./uninstall.sh
```

默认卸载删除程序和 systemd，但保留 `/etc/smartbag`、`/var/lib/smartbag` 与事件。
