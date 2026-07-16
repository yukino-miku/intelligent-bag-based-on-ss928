# sanda-tt/ss928 来源仓库功能清单

审计来源：`https://github.com/sanda-tt/ss928`，ref `codex/dx-gp21-tracker`，固定提交 `d7e10fd06dc553f94d2db3a3d19987ec8648f7dc`。来源仅作读取和选择性迁移，没有合并 Git 历史，也没有向来源仓库提交。

## 平台与 MPP

资料中的 SS928、Hi3403、SD3403 是同一平台系列在芯片、产品和 SDK 文档中的不同命名，实际编译必须以板端 SDK 宏和库版本为准。来源代码面向 Ubuntu 22.04 板端用户空间。MPP 示例入口覆盖 VI 摄像头采集、VPSS 图像处理、VO 显示、VENC 编码、AUDIO、SVP 和 OpenCV；本仓库只迁移独立的 IMX347 preview 示例，不复制 SDK、MPP Sample 树或二进制。

IMX347 使用 EULER_4SEN V1.0 的 sensor0、2lane、I2C7，链路为 `VI -> VPSS -> VO -> MIPI`。在板端设置 `MPP_SAMPLE_ROOT=/path/to/mpp/sample make`，运行生成的 `imx347_mipi_preview`。它依赖厂商 MPP 头文件、库、sensor 驱动和当前板卡 pinmux。

## BMI270 与跌倒检测

BMI270 使用 40Pin Pin3/Pin5 的 I2C0，地址由 SDO 决定为 `0x68` 或 `0x69`。正式 Python 模块支持 Linux IIO 和用户态 I2C、probe/list-iio、姿态、运动趋势、阈值告警、模拟输入和 systemd 部署。六轴积分速度只能描述短时趋势，不能当作可靠绝对速度。BLE 已改为默认关闭，由统一 board service 输出。

旧 `bmi270_i2c_pose` C 工程只保留为寄存器和接线诊断，不作为正式服务。`calibration_analysis.md` 已迁移为 `bmi270-calibration-analysis.md`，原始 calibration CSV 未复制。独立 fall detector 使用 `normal -> possible_fall -> fall_confirmed/impact_only` 状态机；整合桥直接把 BMI270 样本转换为 `ImuSample`，不再通过文本重复解析。跌倒事件与交通风险是不同事件类型。

## DX-GP21

DX-GP21 使用 UART4 Pin8/Pin10 和 `/dev/ttyAMA4`，校验 NMEA checksum，解析 GGA/RMC/VTG，输出 WGS84 定位并保存 JSONL 轨迹。保留模拟模式和旧 BLE 命令 `TL/TG/TF/TS`，统一命名空间为 `GNSS TL`、`GNSS TG <i> <offset>`、`GNSS TF 1`、`GNSS TS`。独立 BLE 默认关闭。

## 震动、音频和 BLE

SmartBag Alert Controller 接收单行 `vision_alert` JSONL，四路 PWM 分别控制左右两组电机，等级 0 到 4。视觉事件只使用稳定后的 haptic level；超时、detector 退出、异常和信号退出都会清零。MAX98357 使用 Pin12 BCLK、Pin38 WS、Pin40 DIN，音频默认关闭并异步播放。统一 BLE 广播名为 `SS928-SmartBag`，提供 AL/GNSS/IMU/SYS 命令路由，避免 GNSS、BMI270 和控制器同时注册 NUS。

## 其他模块

- MT5710：来源提供 5G 语音呼叫辅助脚本，作为可选工具迁移，不进入默认启动链。
- 微信小程序：保留首页、GNSS 轨迹、BMI270 姿态、monitor、tracks、BLE NUS、WGS84 到 GCJ-02、alarm/track 工具和测试；删除默认云开发脚手架与未引用页面。
- 板端调试：保留 SSH/SFTP 上传、命令、service 状态和日志工具；移除固定 IP/密码，改用环境变量。
- `ld2417-radar-web` 与 `radar_uart_test`：属于雷达实验，不参与当前纯视觉风险决策，因此不迁移。
- skills 包装层、`agents/openai.yaml`、`agent.md`：属于代理工作流元数据，不是运行时功能，不迁移；只提取可运行工具并改写普通 README。

## SSH、上传、启动和日志

`06_software/tools/board_debug/board_debug.py` 使用 Paramiko 做 SSH/SFTP 探测、上传、远程命令、服务启动/停止、`systemctl status` 和 `journalctl` 日志读取。主机、用户名和密码分别从 `SS928_BOARD_HOST`、`SS928_BOARD_USER`、`SS928_BOARD_PASSWORD` 获取，不写入仓库；正式环境优先使用 SSH key。统一运维入口是部署包的 `start-all.sh`、`stop-all.sh`、`status.sh` 和 `logs.sh`。
