# MT5710 5G 模块

MT5710 通过 USB 暴露 PCUI 串口和 NCM 网卡，不占用 40Pin。正式 `smartbag-connectivity.service` 只负责拨号、DHCP、CloudBase 主机路由和连接保持，不启动 BMI270 或 GNSS。

在 `/etc/smartbag/smartbag.env` 设置 `SMARTBAG_CONNECTIVITY_ENABLED=1` 和实际 PCUI 设备，例如 `/dev/ttyUSB1`。上传 token、短信号码只放在该 root-only 文件，不提交 Git。5G 或 CloudBase 失败时，本地双摄、风险、震动和灯光必须继续工作。
