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
