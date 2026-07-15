# DX-GP21 接线

接线以 [40pin-usage.md](40pin-usage.md) 为准：模块 TX 接 Pin10/UART4_RXD，模块 RX 接 Pin8/UART4_TXD，并共地。Linux 设备为 `/dev/ttyAMA4`。运行前确认模块电平与板卡 UART 电平兼容，不要把 RS-232 电平直接接到 TTL UART。
