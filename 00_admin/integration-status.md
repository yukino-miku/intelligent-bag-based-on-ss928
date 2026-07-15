# SS928 板端整合状态

## 已完成

- 选择性迁移 IMX347、BMI270、跌倒检测、DX-GP21、震动控制器、小程序和调试工具。
- 视觉 detector 支持 board profile、稳定 haptic JSONL、单摄方向推断、事件限流/清零和后端接口。
- Controller 支持单摄/双摄、四路 PWM 配置、事件过期校验、detector 退出清振和统一 BLE 路由。
- GNSS/BMI 默认不注册 BLE；统一设备名为 `SS928-SmartBag`。
- 建立 40Pin 唯一事实源、部署目录和跨模块协议测试。

## 仍需真实硬件验证

- IMX347 sensor 驱动、MPP 版本、lane mode 和显示链。
- `/dev/video0` 首帧与板端 CPU profile 的真实 FPS/温度。
- PWM sysfs 编号、四路方向、电机驱动供电和退出清零。
- BMI270 IIO；用户态 I2C 需要另行提供合法 `bmi270_config.bin`。
- DX-GP21 UART 波特率、NMEA 连续性和天线环境。
- BlueZ NUS 注册、手机真机、小程序权限和命令往返。
- MAX98357/MT5710；音频默认关闭且仓库不含来源不明音频。

## 未完成

- `Ss928OmBackend` 没有真实 MPP/SVP/NPU API，只保留接口和明确错误。
- 厂商 SDK、MPP Sample、模型转换工具和 `.om` 未纳入仓库。
- 来源仓库没有发现根 LICENSE，公开再分发边界仍需所有者确认。

## 本地验证结果

- Python：181 项通过（视觉 134、录像工具 8、controller 6、GNSS 6、BMI270 6、fall detector 6、跨模块 15）。
- 小程序：2 个 Node 测试脚本、8 项断言通过。
- `compileall` 通过；13 个 JSON 可解析；9 个 shell 脚本通过 `sh -n`。
- systemd 路径和默认 supervisor/diagnostic 互斥关系由集成测试检查；Windows 环境没有执行真实 `systemd-analyze`。
