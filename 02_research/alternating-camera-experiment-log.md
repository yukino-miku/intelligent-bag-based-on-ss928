# 双 USB 摄像头交替采集实验日志

## 2026-07-19 SS928 板端

板端环境：SS928V100、Ubuntu 22.04.1、aarch64、Linux 4.19.90、4 核 CPU、约 953 MiB 内存、无 swap。所有实验使用原生 `v4l2_stream_toggle`，两摄像头通过 `by-path` 区分。

| 组别 | Session | 请求 | 实际协商 | 时长 | 切换 | 成功率 | p50/p95/p99 切换 ms | 最大盲区 ms | 左/右有效 FPS | RSS 峰值 MiB | CPU 峰值 % | ENOSPC |
|---|---|---|---|---:|---:|---:|---|---:|---|---:|---:|---|
| A1 | `20260719-092215_ss928_v4l2_640x480_5fps` | 640x480@5 | 640x480@30 | 120.517 s | 247 | 100% | 248.429 / 278.018 / 278.588 | 514.425 | 4.116 / 4.082 | 27.445 | 4.081 | 否 |
| A2 | `20260719-092507_ss928_v4l2_640x480_10fps` | 640x480@10 | 640x480@30 | 120.183 s | 247 | 100% | 245.259 / 273.899 / 275.576 | 509.928 | 4.127 / 4.094 | 27.418 | 4.281 | 否 |
| A3 | `20260719-092739_ss928_v4l2_320x240_5fps` | 320x240@5 | 320x240@30 | 120.100 s | 247 | 100% | 245.866 / 273.726 / 276.187 | 539.016 | 4.130 / 4.097 | 23.402 | 4.093 | 否 |
| A4 | `20260719-093233_ss928_v4l2_320x240_10fps` | 320x240@10 | 320x240@30 | 120.256 s | 248 | 100% | 248.052 / 273.919 / 274.941 | 513.436 | 4.125 / 4.125 | 23.410 | 3.934 | 否 |
| B | `20260719-093511_ss928_v4l2_640x480_10fps` | 640x480@10 | 640x480@30 | 30.515 s | 49 | 100% | 248.029 / 275.423 / 278.189 | 512.631 | 3.277 / 3.146 | 27.586 | 1.998 | 否 |
| A5 | `20260719-095854_ss928_v4l2_1680x1050_10fps` | 1680x1050@10 | 1920x1080@30 | 30.062 s | 61 | 100% | 250.849 / 278.613 / 279.814 | 509.999 | 4.125 / 3.992 | 54.836 | 5.023 | 否 |
| A6 | `20260719-112904_ss928_v4l2_640x480_30fps` | 640x480@30 | 640x480@30 | 1800.247 s | 3620 | 100% | 252.404 / 275.332 / 283.061 | 580.264 | 4.022 / 4.022 | 33.539 | 7.716 | 否 |

四组首帧 p95 均约 68.2 ms。320x240 降低了约 4 MiB RSS，但没有显著改善切换或首帧时延。请求 5 FPS 和 10 FPS 均被驱动协商为 30 FPS，因此后续应把 640x480@30 作为真实输入条件记录，应用层有效侧 FPS 约为 4.1。

A5 是对 `1680x1050 MJPEG @10 FPS` 的额外短测。摄像头格式表没有 1680x1050，驱动选择了 1920x1080@30；因此不能声称 1680x1050 设置成功。交替采集仍未出现 ENOSPC，但 RSS 峰值升至 54.836 MiB，且这只是 30 秒无模型测试，不代表板端 YOLO 在 1080p 下可用。

## B 阶段接口验证

- `/api/v1/status`：HTTP 200，返回 active camera、切换统计、左右帧龄和 `live/cached/offline` 状态。
- `/api/v1/camera/left/snapshot.jpg`：HTTP 200，JPEG 49,904 bytes。
- `/api/v1/camera/right/snapshot.jpg`：HTTP 200，JPEG 47,720 bytes。
- `/`：HTTP 200，浏览器调试页可读取。
- gateway 只读取调度器缓存，不重新打开摄像头。
- 结束后 `/dev/video0`、`/dev/video2` 无占用进程。

## 参数决定

暂定后续 C 阶段起点为 640x480、实际 30 FPS、500 ms 正常时间片、2 个预热帧、每片 4 个有效帧。A2 的 p95 略优，但差异很小，不能据此声称请求 10 FPS 比 5 FPS 更快。

## 下一轮

1. 安装或构建板端 OpenCV、torch、Ultralytics 和 lap 后，运行单模型 C 阶段短测。
2. 记录推理导致的真实最大盲区；若超过 1200 ms，先减小 `imgsz` 或每片推理帧数。
3. 纯采集 30 分钟已通过；C/D 短测通过后仍需重新运行包含完整视觉链的 10 分钟和 30 分钟测试。
4. 板端没有可读温度节点，本轮温度为 `null`；后续需确认 SS928 温度传感器 sysfs 路径。

## C/D 当前验证边界

- PC 使用真实 `yolo11n.pt` 和 Ultralytics 包内测试图片完成共享模型冒烟：YOLO 对象 1 个，左右 BoT-SORT 实例不同；左侧连续两次输入保持本侧 ID，右侧没有复用左侧 tracker 历史。
- 无硬件测试验证左右 context 的 tracker、标定、StableTrackId、TrackState、RiskModel、stabilizer、SelfObjectFilter 和 risk logger 均不是同一对象；发现共享可变对象会拒绝启动。
- C 运行时在每批原始帧采集后立即 STREAMOFF，再做 JPEG decode、predict、tracker 和 risk；`performance.csv` 分开记录 inference/tracking/risk，`camera-events.csv` 记录 decode。
- D 自动测试验证：切换到另一侧不会自动清前侧；heartbeat 刷新 PWM 但不触发音频/手机历史；stale observation、detector 退出和 level 0 会清振。
- 上述 C/D 尚未在 SS928 上运行。原因是板端缺少 `cv2`、`torch`、`ultralytics` 和 `lap`，不能把 PC 结果写成板端推理性能。

## A6 30 分钟纯采集

- 3620/3620 次切换成功，左右各 7240 帧，有效 FPS 均为 4.022；无 ENOSPC、STREAMON/OFF 失败、首帧超时、相机错误或进程重启。
- capture-only 最大盲区为 580.264 ms。该 session 没有解码、YOLO、tracker、风险、overlay 或 JPEG 重编码，因此 `end_to_end_*` 为 0/null，不能把 580.264 ms 当成完整视觉 E2E。
- CPU 平均/峰值 2.960%/7.716%，RSS 平均/峰值 30.471/33.539 MiB；温度节点不可用，保持 `null`。
- performance CSV 首末 RSS 增加 6.301 MiB。长测后已把内存遥测历史改成有界 deque，并以累计量保留精确总数、均值和峰值；该修复尚未再跑第二个 30 分钟 session。
- 原始 session tar 只保存到 Git 忽略的 `08_media`，SHA256 为 `7F076DD52647FD97C73581B7D6F8BE7408985061FCF1E86A542479E010F0A523`。

## 网关与断连恢复

- 板端本机 status/cameras/左右 status 和左右 raw 均 HTTP 200；无模型时左右 overlay 返回 503。当前只有 USB-UART，无可用网络链路，因此没有完成 PC 浏览器到板端的真实访问。
- 对 sysfs USB 设备 `3-1.3`、`3-1.4` 分别做逻辑 unbind/rebind，恢复时间约 3023.537/2998.492 ms；另一侧继续采集，恢复后双侧回到约 4 FPS。这不是人工物理拔插。
- 故障注入必然产生失败切片，所以该 session 的整体成功率为 93.407%、退出码 2；它用于验证恢复，不作为无故障稳定性验收。
- 测试发现 recorder 没有按侧汇总 reconnect，修复后 50.205 秒复测正确记录 `camera_reconnects=1`，一次左侧逻辑断连恢复耗时 1717.290 ms，结束后两设备无占用。

## 依赖安装尝试

- 板端 Python 3.10.12 缺少 `cv2/numpy/torch/torchvision/ultralytics/lap/pip`。
- `eth0` 为 `linkdown`，DNS 不可用；带 45 秒 timeout 的 APT update 返回 124，报错 `Temporary failure resolving 'mirrors.tuna.tsinghua.edu.cn'`。
- APT 索引虽有 OpenCV 4.5.4、NumPy 1.21.5 和 pip 22.0.2 候选，但本地 cache 没有这些 deb；`10_archive` 也没有 cp310/aarch64 wheelhouse。因此没有伪造安装结果或直接安装未核对 ABI 的最新版包。
