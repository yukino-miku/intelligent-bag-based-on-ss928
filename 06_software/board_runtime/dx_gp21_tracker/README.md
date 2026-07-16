# DX-GP21 GNSS 轨迹服务

模块通过 UART4 `/dev/ttyAMA4` 读取 NMEA，验证 checksum，解析 GGA/RMC/VTG，输出 WGS84 定位并把轨迹保存为 JSONL。

接线：DX-GP21 TX -> Pin10/UART4_RXD，RX -> Pin8/UART4_TXD，共地。详见 `04_hardware/ss928/40pin-usage.md`。

```sh
cd /root/smartbag/gnss
python3 dx_gp21_tracker.py --simulate --once --no-ble
python3 dx_gp21_tracker.py --config config.ss928_uart4.json --command-stdin --no-ble
```

轨迹默认写入 `/var/lib/smartbag/tracks`。默认不注册独立 BLE；统一命令为 `GNSS TL`、`GNSS TG <i> <offset>`、`GNSS TF 1`、`GNSS TS`，旧 `TL/TG/TF/TS` 仍由 controller 兼容路由。
