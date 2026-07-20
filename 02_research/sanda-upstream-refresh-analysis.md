# sanda-tt/ss928 上游刷新审计

审计日期：2026-07-20。

## Git 基线

- 目标仓库：`yukino-miku/intelligent-bag-based-on-ss928`。
- 目标起始分支：`agent/alternating-dual-camera`。
- 目标起始提交：`a5f6d815b924129fca03c8392912f31b843da636`。
- 本轮工作分支：`agent/sanda-hardware-refresh`。
- 上次已确认导入基线：`sanda-tt/ss928@d7e10fd06dc553f94d2db3a3d19987ec8648f7dc`，来源 ref 为 `codex/dx-gp21-tracker`。
- 已知上游 main 与实际 GitHub API HEAD 均为 `970351c84a12f3219e7910ee488ac5ff579d6f98`，没有发生静默前移。
- 比较范围：`d7e10fd0..970351c8`，上游领先 19 个提交，GitHub compare 返回 300 个变更文件。
- 本机原先没有第二份队友仓库。创建了跳过 LFS 的临时 partial clone，但 Git 原生 fetch 遇到 443 连接重置；审计改用 GitHub Git Tree/Contents/Compare API，固定到上述提交并记录 blob SHA。

## 新增提交概览

19 个提交可分为四类：仓库忽略规则与资料整理；大量板卡/SDK/厂商资料；CloudBase 和小程序数据读取；MR20、TM6605、TCA9548A 与 PWM 灯光实验。资料提交不等于许可可分发，也不等于当前硬件已经验证。

关键功能提交：

- `14f6d455`：CloudBase 函数和测试。
- `e7d2e6d9`、`5e9ed8fc`：小程序轨迹和姿态云端读取。
- `4f53cde5`：MR20 初版。
- `ed54faf6`、`970351c8`：TM6605、灯光和雷达控制实验。

完整提交 SHA 与逐文件决策见 `00_admin/sanda-upstream-import-manifest.json`。

## 目标仓库主架构

目标仓库现有固定双摄和交替双摄、原生 V4L2 STREAMON/OFF、单模型双 tracker、左右独立 TrackState/RiskModel/stabilizer、Future Conflict Gate、CPA、moving-away、多帧跨 slice 确认、raw/visual/haptic 分层、状态变化与 heartbeat、stale/exit clear、相机重连、统一 BLE、GNSS/IMU 路由、HTTP/MJPEG 和小程序双摄页面均保留。

上游只作为新硬件行为参考。旧 `AlertEvent`、`AlertState`、`DetectorProcess`、BLE router、controller、systemd service 和小程序页面不得覆盖目标实现。

## 功能审计

### TCA9548A 与 TM6605

上游 `tm6605_haptics.py` 证明了以下行为：TM6605 7 位地址为 `0x2d`；效果寄存器 `0x04`；播放寄存器 `0x0c`；双同址模块需要 mux；Level 3/4 使用 effect 15/14 的调度思路。

不能直接复制的原因：使用 `/tmp/ss928-i2c0-mux.lock`，与本轮统一锁路径不一致；效果寄存器和播放寄存器由两个独立锁事务写入，中间可能被 BMI270 或另一侧切换 mux；没有统一读事务、锁等待指标和错误计数；等级参数是模块常量。决策为 REIMPLEMENT/ADAPT：在 `board_runtime/common` 建立完整事务锁，在目标 controller 中实现可配置后端。

### PWM 灯光

上游 `pwm_lights.py` 提供左右 Pin7/Pin32 的调度意图，但把 `pwmchip0` 和 channel 10/1 视为固定事实，export 后不等待节点，也没有处理旧 duty 大于新 period 导致的 `EINVAL`。决策为 REIMPLEMENT：运行时发现 pwmchip/channel、按 disable -> duty 0 -> period -> duty -> enable 顺序写入，错误必须进入状态。

### MR20

上游 MR20 代码包含 14 字节帧、0x60A/0x60B、官方样例解码、来源 IP 过滤、scan 聚合和简单多帧风险。解析公式和匿名化测试帧可作为行为参考。

风险与缺口：上游接收器没有严格校验来源端口；未知帧通常作为异常丢弃而非分类统计；旧 AlertState 仅按 side 保存，雷达 clear 会误清仍有效视觉；实测只证明物理链路、ping、UDP 以及 0x60A/0x201/0x700，未证明 0x60B 目标告警闭环。决策为 ADAPT/REIMPLEMENT，雷达默认可选且不参与视觉风险模型内部计算，只以独立 source level 进入 controller 的 max-by-side 融合。

### BMI270

目标仓库版本已保留姿态、趋势、IIO/I2C、跌倒桥、BLE 命令和校准。上游新增版本仍包含二进制 config blob 和独立启动脚本。只适配 mux 参数和共享事务层，不覆盖现有算法，不复制 `bmi270_config.bin` 或 calibration CSV。

### CloudBase

上游 cloud source 和函数只能作为需求证据，不能直接迁移：

- `app.js` 硬编码 EnvId。
- app API 固定 `DEVICE_ID = "bag001"`，没有 `OPENID + deviceId` 绑定检查。
- ingest 固定 fallback EnvId，仅用共享 upload token，没有 timestamp、nonce、HMAC、body SHA256 或重放保护。
- 轨迹和告警固定读取 100 条，没有 cursor 分页。
- 首页写死在线状态。

决策为 REIMPLEMENT：示例配置默认关闭；云函数从 `cloud.getWXContext()` 取得 OPENID；设备上传使用 HMAC-SHA256、timestamp、nonce 和 body hash；本地 uploader 使用有界队列和指数退避；CloudBase 不替代 BLE，也不承载连续视频。当前无 CloudBase 凭据，本轮只能做到 IMPLEMENTED/UNIT TESTED，必须标记 NOT DEPLOYED。

### 厂商资料和大文件

`01. 快速使用指南【必看】`、`02. 硬件连接与功能测试`、`07硬件资料`、`在线仓库`、`补充资料`、模型、镜像、SDK、PDF、RAR/ZIP、DXF/BRD、LFS 对象和已编译二进制全部 REJECT。MR20 资料只登记文件名和结论，不复制。来源仓库根目录未发现明确 LICENSE，因此队友自编代码也记录为 `license_status=unknown`，采用行为重实现并保留来源说明，不能声明可自由分发。

## 实施边界

- 新 profile：`rev2_tm6605_mr20`，默认 TM6605；兼容 profile：`legacy_pwm_haptics`。
- Pin3/5 只作为 I2C0 到 TCA9548A；CH0 BMI270，CH1 左 TM6605，CH2 右 TM6605。
- Pin7/32 在 Rev2 中只用于左右灯光，不再驱动旧 PWM 振动；旧 profile 保持原映射，两个 profile 不并发。
- MR20 使用 `eth1`、`192.168.1.102/32` 到 `192.168.1.200/32` 的 host route，不修改 eth0、默认路由或网关。
- GNSS UART4 和 MAX98357 I2S 引脚保持不变。
- 所有真实硬件和 Cloud 结论必须分别标记 BOARD TESTED、PHYSICALLY VERIFIED、CLOUD DEPLOYED 或 BLOCKED。
