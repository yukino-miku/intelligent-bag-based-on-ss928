# SS928 智能背包整合架构

## 正式数据链

```text
left fixed USB camera  -> left detector  -> stabilized haptic vision_alert --+
right fixed USB camera -> right detector -> stabilized haptic vision_alert --+--> AlertState(source, side)
optional left/right MR20 UDP workers ----------------------------------------+
                                                                                |
                                                                                v
                                                max effective level per side
                                                                                |
                          +---------------------+-------------------+-------------+
                          v                     v                   v
                 TM6605/LRA via TCA       Pin7/Pin32 lights   optional MAX98357
                          |
                          +--> unified BLE NUS (SS928-SmartBag) --> mini program

BMI270 single owner -> posture/fall fusion -> posture reminder / CloudBase / optional SMS or call
DX-GP21 optional    -> valid WGS84 track    -> local cache / CloudBase / controller command route
MT5710 service      -> NCM connectivity only; failure does not stop local warning
Tsensor service     -> explicit ok/invalid/unavailable temperature JSON
```

## 唯一硬件所有者

| 资源 | 唯一正式所有者 | 约束 |
|---|---|---|
| 左/右 USB camera | 对应固定 detector | gateway 只代理 detector latest frame，不重新打开设备 |
| BLE/BlueZ NUS | Alert Controller | BMI270、GNSS 默认 `--no-ble`；WS73 unit 只加载内核模块 |
| BMI270 | Controller 启动的 IMU 子进程 | 禁止另启旧 BMI service；I2C0 使用 TCA channel 0 |
| 左/右 TM6605 | Alert Controller | TCA channel 1/2；与 BMI 使用同一跨进程锁 |
| 左/右灯 | Alert Controller | Pin7/Pin32；Pin35/Pin37 仅保留 legacy PWM 兼容 |
| MR20 UDP ports | Controller 内 MR20 workers | 每个雷达独立 bind port、radar IP、side 和 source |
| MAX98357 | Alert Controller AudioPlayer | 默认关闭，异步播放，不能阻塞振动 |
| MT5710 NCM | `smartbag-connectivity.service` | 不再启动或复制 BMI/GNSS 采集进程 |

## 告警语义

视觉输出分为 `raw_risk_level`、`visual_risk_level`、稳定后的 `haptic_risk_level`。Detector 的 JSONL 只发送 haptic level。Controller 以 `(source, side)` 保存状态，同侧取最大等级；某一来源的 `level=0`、退出或超时只清该来源，不清除其他来源。

驼背提醒使用独立 `posture:hunch` 来源，默认双侧 level 1、5 秒，可选播放 `bad` 音频。跌倒/撞击事件与交通风险是不同事件类型，不直接映射为视觉 DANGER；只有最终确认的严重跌倒才允许 CloudBase、短信或电话通知。

## 故障隔离

- detector 退出：立即清除该 detector 对应来源和侧别，有限退避重启；另一侧继续。
- malformed/stale/out-of-range event：丢弃并记录，不驱动输出。
- Controller 启动、SIGTERM/SIGINT、异常和 systemd stop：`safe-off` 关闭 TM6605、灯和 legacy PWM。
- CloudBase/MT5710/GNSS 故障：本地检测、跟踪、风险和震动继续运行。
- GNSS 无 fix 或缓存过期：省略位置，不使用假坐标。
- 温度读取失败：返回 `invalid`/`unavailable`，不伪造温度。

## NPU 边界

当前正式实时链仍是 Python `DetectorBackend`/Ultralytics 路径。来源 NPU 代码已收敛为离线 raw-NV12 到 detections JSONL 的实验后端，并通过不依赖 ACL 的 native contract/preprocess/decode tests。来源实板证据仅证明固定输入 ACL 运行，且工厂 OM 未产生可信目标；USB 实时采集、双路调度、detections 到 BoT-SORT/风险的实时桥接仍未验收。因此部署不得把 OpenVINO 或离线 ACL runner 写成已完成的 SS928 NPU 实时后端。
