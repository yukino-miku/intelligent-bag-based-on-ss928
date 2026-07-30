# 离线 Release 包

从已提交的 tag/commit 构建 RC2：

```sh
OUTPUT_DIR=/tmp/smartbag-release \
  ./09_deliverables/releases/build-release.sh smartbag-v1.0.0-rc2 HEAD
cd /tmp/smartbag-release
sha256sum -c SHA256SUMS
```

输出：

- `smartbag-ss928-v1.0.0-rc2.tar.gz`
- `SHA256SUMS`
- `release-manifest.json`
- `dependency-manifest.json`

归档包含正式 OM、模型 manifest、AArch64 runner/inspector、runner manifest、安装器、配置/标定向导、systemd、License 和第三方声明；明确排除 `08_media`、`10_archive`、个人视频、日志、SDK、ACL runtime、工具链和 secret。

```sh
tar -xzf smartbag-ss928-v1.0.0-rc2.tar.gz
cd smartbag-ss928-v1.0.0-rc2
sudo ./install-on-ss928.sh --interactive
```

`clone_install_ready=true` 表示交付包自包含并通过干净克隆/mock 安装，不代表真实板端、reboot 或独立供电已经通过。后者继续保持 `PENDING/false`，直到上传相应非敏感证据。
