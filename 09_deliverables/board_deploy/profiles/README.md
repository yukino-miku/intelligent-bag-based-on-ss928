# 硬件 Profile

Profile 是对 `/etc/smartbag/config.json` 的递归覆盖，不包含密码、手机号、CloudBase token、设备 IP 或本机摄像头路径。默认安装不自动套用 profile；仅在首次安装时可通过 `SMARTBAG_HARDWARE_PROFILE` 指定。

- `dual-usb-base.json`：正式基线，固定左右 USB 双摄、BMI270、TM6605/LRA 和灯光；MR20、GNSS、音频关闭。
- `dual-usb-full.example.json`：全部可选模块示例，只能在接线、供电、端口和驱动验证后使用。

手工应用到已有配置前应先备份：

```sh
cp /etc/smartbag/config.json /etc/smartbag/config.json.bak
python3 apply_hardware_profile.py /etc/smartbag/config.json profiles/dual-usb-base.json
```
