# sanda-tt/ss928 全量审计与整合计划

## 固定基线

- 目标仓库：`yukino-miku/intelligent-bag-based-on-ss928`
- 目标基线分支：`agent/ss928-board-integration`
- 目标基线 SHA：`06c6cfd1dc11a0f92c54ce8aad5252d554ececa5`
- 整合分支：`agent/full-sanda-integration`
- 只读来源：`sanda-tt/ss928`
- 来源 SHA：`59071297e5d8f339332a7234406429f94ffe2570`
- 来源 Git blob 数：24,421；来源无 tag。

未使用 unrelated-history merge，也未修改来源工作树。完整逐文件决定由 `sanda-full-file-manifest.csv` 记录；生成器和校验器位于 `06_software/tools/sanda_integration/`。

## 审计口径

1. 使用 `git ls-tree -r -z -l` 遍历来源提交，不依赖工作树是否能 checkout LFS。
2. 对每个 blob 读取 Git 对象、计算 SHA-256、文件类型、模块、用途、目标落点和动作。
3. 校验器重新读取全部 Git blob，核对路径一一对应、大小、SHA-256、动作集合和目标路径安全性。
4. 5 个 Git LFS pointer 的对象内容未在来源 checkout 中取得，只记录 OID/声明大小并标为 `BLOCKED`；不伪造内容。
5. `handoff.md` 含设备 IP/密码交接信息，原文不迁移，标为 `BLOCKED`。
6. SDK、在线仓库镜像、厂商资料和大量 sample 以来源提交作为可追溯索引，记为 `ARCHIVE`，不复制进正式运行树。

## 整合原则

- 目标仓库现有视觉检测、BoT-SORT、测距/测速、Future Conflict Gate、多帧稳定、visual/haptic 分层、自身前景过滤和双固定 USB 摄像头架构是权威实现。
- 不恢复“单模型左右交替采集”作为正式模式，不让第二个进程重复打开摄像头。
- 来源有效功能进入现有目录分类；旧入口、旧 service、临时 staging 和重复实现归并到唯一入口。
- SS928 NPU 只迁移可验证的 ACL/OM 检测原语和诊断证据，不伪造尚未完成的实时后端。
- 默认风险仍以视觉 `haptic_risk_level` 为准；MR20 是可选、默认关闭的独立告警来源，不修改视觉风险模型。
- Secret、手机号、Cloud token、板端密码、真实标定、模型和本地设备 IP 不提交。

## 功能落点

| 来源能力 | 正式落点 | 整合方式 |
|---|---|---|
| MR20 左右 UDP 雷达 | `06_software/board_runtime/mr20_radar` | parser/worker 合并，Controller 按 source+side 融合，默认关闭 |
| TCA9548A + TM6605/LRA | Controller + `common/i2c_mux.py` | BMI270/TM6605 共用跨进程锁，通道 0/1/2 隔离 |
| 左右 PWM 灯 | `pwm_lights.py` | Pin7/Pin32，Controller 唯一所有者 |
| BMI270 姿态/驼背/跌倒 | `bmi270_backpack` + `imu_fall_detector` | 单采集进程；驼背提醒接入双侧轻振和可选 `bad` 音频 |
| DX-GP21 | `dx_gp21_tracker` | 可选，默认无 BLE；无有效定位时不伪造坐标 |
| MT5710 | `mt5710_connectivity` | 正式服务仅管理 NCM；短信/电话由最终跌倒事件按配置调用 |
| CloudBase | `cloud_uploader` + 小程序 cloudfunctions | 异步、失败不阻塞本地预警；token/env 外置 |
| Tsensor | `05_firmware/ss928/tsensor` + `temperature` | 驱动源码保留，`.ko` 不提交；读取失败返回明确状态 |
| SS928 OM/NPU | `vision_obstacle_tracker/ss928_backend` | 离线 detection JSONL 原语；实时 tracker/risk bridge 仍待实板验收 |
| 微信小程序 | `06_software/mobile/ssminiprogram` | 保留已有页面，新增云端姿态/告警和统一 BLE remote |
| CAD/提交工具 | `04_hardware/ss928/cad`、`09_deliverables/sanda_submission_reference` | CAD 作为项目资产；只保留可重建文档的生成脚本 |

## 验证与提交

最终验证包括 Python compileall、各模块 unittest、跨模块集成测试、11 个小程序/CloudBase Node 测试、C++ native tests、JSON、shell `sh -n`、systemd 路径、manifest 全 blob 校验、secret/大文件/生成物扫描和 `git diff --check`。真实板不可达或缺少 SDK/硬件时必须记录为未验证，不用模拟结果代替。
