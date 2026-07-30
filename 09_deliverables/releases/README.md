# 离线发布包

在最终提交或 tag 上执行：

```sh
09_deliverables/releases/build-release.sh smartbag-v1.0.0-rc1 smartbag-v1.0.0-rc1
```

生成 `smartbag-ss928-v1.0.0-rc1.tar.gz` 和 `SHA256SUMS`。包内包含正式运行源码、AArch64 runner、systemd、配置、profile、音频和安装器，不包含 `08_media`、`10_archive`、厂商 SDK、ACL runtime、secret 或当前许可证受阻的 YOLO11n OM。

离线板端使用：

```sh
sha256sum -c SHA256SUMS
tar -xzf smartbag-ss928-v1.0.0-rc1.tar.gz
cd smartbag-ss928-v1.0.0-rc1
sudo ./install-on-ss928.sh --offline --radar-only --yes
```

发布包 manifest 明确保留 `full_install_ready=false`，不能把 radar-only 包描述为完整雷视融合验收包。
