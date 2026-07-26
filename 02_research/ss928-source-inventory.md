# sanda-tt/ss928 来源功能清单

审计来源固定为 `sanda-tt/ss928@59071297e5d8f339332a7234406429f94ffe2570`。本文件说明可识别功能；每个文件的决定见 `00_admin/sanda-full-file-manifest.csv`。

## 平台与资料

SS928V100 是芯片/平台标识，Hi3403/SD3403 是相关产品/板卡资料中出现的命名；实际兼容性必须以板上 `uname`、SDK/MPP 版本、动态库和 sample 编译结果为准，不能仅按名称互换。来源运行背景是 Ubuntu 22.04/aarch64、Linux 4.19 系列板端环境。

来源的厂商资料和在线仓库镜像包含 MPP 的 VI、VPSS、VO、VENC、AUDIO、SVP/NPU 和 OpenCV/Python 示例入口。它们用于查接口、编译链和排障，不整体迁入正式仓库。VI/VPSS/VO 或固定输入 ACL 跑通都不能证明本项目的实时检测链已经使用 NPU。

## 摄像头与视觉

### IMX347 MIPI preview

- 硬件：EULER_4SEN V1.0、sensor0、2 lane、I2C7。
- 数据链：`VI -> VPSS -> VO -> MIPI`。
- 来源 `work/imx347_mipi_preview` 包含 C 工程、Makefile 和说明；迁入 `05_firmware/ss928/board_samples/imx347_mipi_preview` 作为诊断 sample。
- Makefile 使用可配置 MPP sample root，不写开发电脑绝对路径；它不进入默认双 USB systemd 链。

### SS928 YOLOv8 VOT/OM

- 有效原语：ACL 模型描述、固定输入检查、NV12 letterbox、YOLO 输出解码/NMS、OM inspect、离线 runner 和诊断脚本。
- 来源证据：固定输入 1/100 帧 ACL 执行成功；100 帧平均 infer 约 25.112 ms、postprocess 约 16.292 ms、总体约 23.348 FPS。
- 失败边界：工厂 OM 对已知图像没有产生可信目标，USB/live stage 未完成；旧 VOT pipeline 与目标现有 fixed-camera/Python tracker/risk 重复。
- 迁入 `vision_obstacle_tracker/ss928_backend` 的是 detection producer 和测试，不替换现有 BoT-SORT、测距/测速、Future Conflict Gate、stabilizer 或 overlay。

## BMI270、姿态与跌倒

### `bmi270_i2c_pose`

低层 I2C probe/寄存器诊断。正式服务已由 `linux_bmi270_backpack` 覆盖，旧 C 工程仅保留独立诊断价值和接线知识，不作为第二采集进程。

### `linux_bmi270_backpack`

- I2C0：Pin3 SDA、Pin5 SCL；地址 0x68/0x69。
- 支持 Linux IIO 和用户态 `/dev/i2c-*`，当前正式 TCA9548A channel 0。
- 提供 probe/list-iio、姿态、运动指标、阈值、校准、simulate、命令 stdin 和测试。
- 姿态输出是短时趋势，不把六轴积分描述成可靠绝对速度。
- 新增累计驼背提醒、每日姿态统计、温度附带、CloudBase 上报和跌倒融合；本地提醒通过 Controller 的 `posture:hunch` 独立来源执行。
- 默认 `--no-ble`，Controller 是唯一 NUS 所有者。

### IMU fall detector

独立状态机处理自由落体、冲击、姿态改变和恢复，输出 `possible_fall`、`impact_only`、`fall_confirmed`。BMI 样本直接转换成 `ImuSample`，不经过重复文本解析。最终跌倒事件与交通风险分开，可触发 CloudBase 和可选 MT5710 短信/电话。

## GNSS

DX-GP21 使用 UART4，默认 `/dev/ttyAMA4`，Pin8 TX、Pin10 RX。解析带 checksum 的 GGA/RMC/VTG，保存 WGS84 JSONL 轨迹，支持 simulate 和 BLE 兼容命令 `TL/TG/TF/TS`。正式部署默认关闭独立 BLE；fix 无效或缓存过期时不上传伪造位置。

## 告警 Controller 与输出

`smartbag_alert_controller` 接收稳定后的 `vision_alert` JSONL。来源新增能力包括：

- 按 source/side 融合视觉和 MR20；每侧取最大有效 level 0..4。
- TCA9548A 后左右 TM6605/LRA，通道 1/2；BMI channel 0；跨进程锁覆盖 mux select+transfer。
- Pin7/Pin32 左右灯；Pin35/Pin37 只作 legacy PWM 兼容。
- MAX98357：Pin12 BCLK、Pin38 WS、Pin40 DIN；音频异步且默认关闭。
- 单一 `SS928-SmartBag` BLE NUS，路由 `AL`、`GNSS`、`IMU`、`SYS`。
- malformed/stale/out-of-range 事件拒绝；启动、退出、异常和 detector death 安全清零。

## MR20

来源 `work/radar` 提供 UDP frame、target parser 和左右后方目标 worker。正式合并模块允许独立 radar IP、bind port、side、连续帧阈值和日志。默认关闭；启用后它是 Controller 的独立 haptic source，不进入视觉风险模型，也不恢复已删除的旧雷达可视化器。

## MT5710 与 CloudBase

### MT5710

支持 PCUI AT 检查、SIM/驻网、APN、NCM interface discovery、DHCP、CloudBase route、UCS2/PDU SMS 和可选限时电话。正式 `smartbag-connectivity.service` 只拥有网络，不再重复启动 BMI/GNSS。手机号、token 从 root-only 环境读取；故障只记录，不阻塞本地预警。

### Cloud uploader

异步上传有效轨迹、姿态/每日统计和最终跌倒事件，采用 bounded queue/latest status，网络失败不抛回传感器主循环。CloudBase function 分为设备 ingest 和小程序 read API，上传 token 与环境 ID 外置。

## 温度

`tsensor_module_build` 含 `/proc/Tsensor` 驱动源和与内核严格匹配的构建文件；不提交 `.ko`。`temperature_runtime_update` 的有效解析已合并到 `board_runtime/temperature`、BMI posture cloud 和 cloud uploader；返回 `ok`、`invalid`、`unavailable`，不造假。

## 微信小程序

正式落点保留/整合：首页、固定左右画面、monitor、tracks、BLE NUS、WGS84->GCJ-02、告警历史、CloudBase 姿态分析/实时页和 remote。默认扫描设备名 `SS928-SmartBag`，使用统一命令命名空间。quickstartFunctions、example、placeholder 外壳、默认素材和 private config 不进入正式 app；有效告警逻辑迁入 `pages/alarms`。

## 工具、CAD 和提交资料

- `ss928-direct-board-debug` 的 Paramiko 工具迁入普通 `board_debug` 工具，不保留 skill metadata，密码只允许环境变量/运行参数。
- MAX98357 `prepare_audio.py` 迁入 `audio_prepare`；部署只保留单套 L1..R4/`bad` AAC，PCM 中间文件删除。
- 3D CAD 移入 `04_hardware/ss928/cad`。
- submission 只保留可重建 DOCX 的脚本，生成文档不提交。

## 未迁移的参考模块

旧 LD2417/radar UART web 实验、完整 SDK/镜像/在线仓库副本、vendor binary、模型、日志、原始 calibration CSV、build/staging 和缺失 LFS 对象不进入正式运行树。其路径、hash、原因均保留在 manifest；来源根目录许可证不清晰，详见 `THIRD_PARTY_NOTICES.md`。
