# MT5710 5G 连通性服务

正式职责只有 MT5710 PCUI/NCM 网络：检查 SIM 和驻网、选择 APN、拨号、动态发现 `cdc_ncm`、DHCP，并确认 CloudBase 目标路由经过该接口。它不拥有 BMI270、DX-GP21、BLE、震动或视觉进程。

```sh
# 只检查并退出
python3 mt5710_connectivity.py --check-only --port /dev/ttyUSB1

# 正式 systemd 行为：建链后驻留，收到 SIGTERM 清理临时 host route
python3 mt5710_connectivity.py --port /dev/ttyUSB1
```

`--supervise-sensors` 只保留旧环境诊断，不进入 `smartbag-connectivity.service`。正式部署由 Controller 启动唯一 BMI/GNSS 子进程，避免重复占用 I2C/UART/BLE。

## 环境与安全

`/etc/smartbag/smartbag.env` 必须 root:root 0600：

```text
SMARTBAG_CONNECTIVITY_ENABLED=1
SMARTBAG_MT5710_PORT=/dev/ttyUSB1
SMARTBAG_UPLOAD_TOKEN=...
SMARTBAG_ALERT_PHONE=...
```

号码/token 不进入 Git。短信和电话只由最终确认的跌倒事件调用；普通交通预警不发送。网络、Cloud、SMS 或 call 失败只写 stderr，不得阻塞本地视觉和振动。无用户明确授权时只运行 fake AT 测试，不发送真实短信或拨号。

## 历史实板证据

来源记录曾验证电信 `ctnet`、动态 NCM、CloudBase route 和 telemetry HTTP 200，也验证过 UCS2/PDU 短信。该记录来自来源提交环境，不能替代本分支、当前 SIM、当前固件和当前接线的复测。

```sh
python3 -m unittest discover -s tests -v
systemctl status smartbag-connectivity.service --no-pager -l
journalctl -u smartbag-connectivity.service -b -n 100 --no-pager
```
