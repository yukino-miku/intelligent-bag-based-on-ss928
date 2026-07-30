# RC2 整合状态

更新时间：2026-07-30。

## 当前正式链路

```text
双 MR20 -> RadarTrackManager -> 共享 RiskModel -> 每目标 0.5 秒中位数 -> Controller
                                  ^
左右 UVC 交替快照 -> 单 OM 车辆分类 -> 当前帧目标关联
```

- full 与 radar-only 共用完全相同的轨迹、CPA/Future Conflict/DRAC、RiskModel 和窗口；radar-only 仅使用 `unknown`、权重 1.0。
- 每次视觉帧原子替换本侧车型映射；未匹配、歧义、过期或视觉故障都回到 unknown，不删除雷达轨迹。
- 正式 L3/L4 需要窗口样本数、观测时长、完整扫描率和雷达质量达标；极近 fast path 仍需连续 2 个高质量样本。
- haptic 稳定结果驱动 TM6605/LRA、灯、BLE 和可选音频；raw/visual 不直接驱动震动。

## 安全和运维

- 管理/只读 API Token 在首装生成并保存为 root 0600；默认只监听 loopback，PATCH/reset 只允许管理 Token。
- 双相机按 USB 物理身份交互分配并建立 udev 链接，任意时刻最多一路 STREAMON。
- MR20 preflight 检查网络、UDP、合法帧和完整扫描；运行期显示 worker/error/restart/scan health，死亡后清零并指数退避重启。
- 危险图片按原始 frame/detection 绘制；原帧不存在时保存 `frame_mismatch`，不会误框新图中的另一辆车。
- 事件默认限制为 500 条、200 张图、256 MiB、30 天；升级和默认卸载保留配置与历史。

## 发布资产

- OM：`09_deliverables/board_deploy/models/vehicle-detector.om`，SHA256 `9e3c448ab7309428ea78cfdc509926404220fa74dd56c89e4995366f5f16af95`。
- runner：`09_deliverables/board_deploy/bin/aarch64/ss928_detection_runner`，AArch64，SHA256 `332c792dc7a64190e182f6260edb455668e1885e883a0e48c794728eed024737`。
- 静态 I/O/预处理/后处理契约通过；真实 SS928 ACL load、descriptor 记录和 OM 同图检测仍是 `PENDING`。
- 仓库采用 AGPL-3.0-only；厂商 SDK、ACL runtime、系统镜像、工具链、secret 和个人视频不分发。

## 本机测试

- Python：395 项，12 个模块/集成测试套件全部通过。
- Node：12 个小程序/CloudBase 测试文件通过。
- Native：4 个 SS928 NPU C++、1 个 C 核心、1 个 C++ backend 通过。
- `compileall`、44 个 JSON、33 个 Shell、secret、模型/runner manifest 和 `git diff --check` 通过。
- GitHub Actions 还会执行干净 clone、full/radar-only mock 安装、重复安装、卸载保留数据和 release 包检查。

## 不得误报为已验证

- `BOARD_INSTALL_VERIFIED=false`：RC2 尚未在当前接线完整安装并运行 30 分钟。
- `POWER_ONLY_AUTOSTART_READY=false`：尚未完成 reboot 后拔除电脑与独立供电冷启动。
- 历史 SS928/UVC 数据仅用于背景，不能代替本版本实测。
- 真机统一执行 `sudo ./validate-on-ss928.sh --full --duration 30m`，并单独记录 reboot/独立供电证据。
