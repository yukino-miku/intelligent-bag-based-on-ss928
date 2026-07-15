# 统一 BLE 协议

默认广播名 `SS928-SmartBag`，由 controller/board service 独占 Nordic UART Service。GNSS 和 BMI270 默认禁用各自 BLE。

命令空间：

```text
AL L1 | AL R2 | AL CLEAR
GNSS TL | GNSS TG <i> <offset> | GNSS TF 1 | GNSS TS
IMU STATUS | IMU ZERO | IMU ZERO_V | IMU SET <key>=<value>
SYS STATUS
```

兼容旧命令：`TL/TG/TF/TS` 路由到 GNSS；`STATUS/ZERO/ZERO_V/SET` 路由到 IMU。默认部署不扫描多个独立 NUS；小程序 legacy/debug 模式可用于旧板端验证。
