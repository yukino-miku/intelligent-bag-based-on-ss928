# SS928 板端调试工具

安装 `paramiko` 后，可通过 SSH/SFTP 探测、上传并管理统一的 `smartbag.target`。仓库不保存板端密码或固定 IP。

```powershell
$env:SS928_BOARD_HOST = "ss928"
$env:SS928_BOARD_PASSWORD = "<board-password>"
py board_debug.py probe
py board_debug.py upload --local D:\path\intelligent-bag-based-on-ss928 --remote /root/smartbag-src
py board_debug.py run "sh /root/smartbag-src/09_deliverables/board_deploy/install.sh /root/smartbag-src"
py board_debug.py status
py board_debug.py logs --lines 120
```

首次连接请先用系统 `ssh` 接受并核对主机指纹；脚本默认拒绝未知主机密钥。

## 仅有 USB-UART 时传文件

板卡没有可用网络、但已经通过串口登录到 Linux shell 时，可以用
`serial_binary_transfer.py` 在 PC 和板卡之间传单个文件。该工具依赖
`pyserial`，传输完成前不会把 `.part` 文件替换为目标文件，并同时校验
PC、板端和传输结果的 SHA-256。

```powershell
py -m pip install pyserial

# PC -> SS928
py serial_binary_transfer.py --port COM3 D:\path\package.tar.gz /root/staging/package.tar.gz

# SS928 -> PC
py serial_binary_transfer.py --receive --port COM3 D:\path\snapshot.jpg /root/staging/snapshot.jpg
```

使用前必须先在普通串口终端中登录，随后退出终端，保证没有其他程序占用
同一个 COM 口。下载时还必须让串口控制台保持安静；内核日志、`udhcpc`
等后台输出会混入原始字节流并导致 SHA-256 校验失败。不要把密码、固定 IP
或设备专用配置写进脚本和仓库。
