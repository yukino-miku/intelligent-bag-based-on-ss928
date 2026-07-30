# 克隆安装就绪度

评估基线为 `agent/radar-primary-vision-class-fusion` 的 `e2c524b69b1613c47921923c7bf3f4dae68c5980`，最终提交信息会在发布记录中补充。机器扫描的逐文件结果见 `local-deployment-asset-inventory.csv/json`。

## 当前结论

- `CLONE_INSTALL_READY=false`：全新克隆可以获得候选 `vehicle-detector.om`，但该候选尚未完成正式许可确认、SS928 descriptor 和检测结果验收，不能视为可部署模型。
- `RADAR_ONLY_CLONE_INSTALL_STATIC_READY=true`：从 GitHub HTTPS 浅克隆 `d2efcff85e91f300373776ce94e6414915422c26` 后，源码、AArch64 runner、双 MR20 配置、执行器配置、systemd 和安装脚本齐全；radar-only 离线包 mock 安装通过，仍需在板上做硬件预检。
- `POWER_ONLY_AUTOSTART_READY=false`：没有完成真实安装、reboot 和拔除电脑后的独立供电测试。

## 18 项缺口

| # | 项目 | 状态 | 处理结果 |
|---:|---|---|---|
| 1 | Python/C/C++/Shell/小程序源码 | READY | 已跟踪，安装器复制正式运行目录。 |
| 2 | 正式车辆模型 | LICENSE_AND_BOARD_VALIDATION_REQUIRED | PT/ONNX/OM 已验哈希；PT/ONNX 同图检测通过，OM 候选已进入 Git，但正式许可、descriptor 和板端检测对齐仍待完成。 |
| 3 | SS928 runner | BOARD_VALIDATION_REQUIRED | AArch64 ELF 已打包，支持 descriptor 自动选择三类输入；ACL 实板待测。 |
| 4 | runner 动态库 | BOARD_VALIDATION_REQUIRED | 只依赖 `libascendcl.so` 和 glibc；ACL 必须来自匹配板端镜像。 |
| 5 | 左右相机 | BOARD_DISCOVERY_REQUIRED | 已知物理端口 1.3/1.4 仅作提示；安装时逐路采集并生成 udev 链接。 |
| 6 | 双 MR20 | BOARD_VALIDATION_REQUIRED | `.200:2368`、`.201:2378` 模板已纳入 profile；需验证真实网络和方向。 |
| 7 | 融合标定 | BOARD_DISCOVERY_REQUIRED | 未找到可证明属于当前安装位姿的外参；提供采样、拟合和 RMSE 校验。 |
| 8 | BMI270 | BOARD_VALIDATION_REQUIRED | IIO/I2C 配置与测试已跟踪；初始化数据和芯片响应需实板确认。 |
| 9 | TM6605/TCA/灯/音频 | BOARD_VALIDATION_REQUIRED | 通道、波形、safe-off 和音频资产已跟踪；输出需实测。 |
| 10 | systemd | READY | units 和 target 路径一致，静态检查后仍需真实启动。 |
| 11 | 安装/升级/卸载/预检/日志 | READY | 配置和用户数据默认保留；完整模式缺资产会非零退出。 |
| 12 | 小程序 | READY | 源码、Node 测试、导入/CloudBase 文档与空模板齐全。 |
| 13 | CloudBase | SECRET_REQUIRED | AppID、环境 ID 和 token 不提交，由部署者本地填写。 |
| 14 | 默认硬件 profile | READY | 版本化事实与“必须发现/必须标定”字段分开记录。 |
| 15 | 一键入口 | READY | `sudo ./install-on-ss928.sh`；模型未接受时用 `--radar-only`。 |
| 16 | 开机启动 | BOARD_VALIDATION_REQUIRED | 安装器执行 enable；没有真实 reboot 证据。 |
| 17 | safe-off | READY | 安装失败、信号和异常退出均请求清零。 |
| 18 | 版本/SHA/依赖 | READY | runner/model/dependency manifest 已有；RC bundle 和 `SHA256SUMS` 已从远程干净克隆生成并校验。 |

## 允许的安装路径

当前唯一不掩盖阻塞项的命令是：

```sh
sudo ./install-on-ss928.sh --radar-only --yes
```

完整模式必须提供通过许可审查且 manifest/descriptor/板端同图结果均通过的模型。安装器不会从 `08_media`、`10_archive` 或电脑备份目录偷偷复制模型。

## 干净克隆证据

- 来源：GitHub HTTPS，`--depth 1 --filter=blob:none --single-branch`。
- 远程提交：`d2efcff85e91f300373776ce94e6414915422c26`。
- 该次 RC1 clone 中不存在 `08_media` 和 `.om`，runner SHA/架构校验通过；这是候选 OM 入库之前的发布证据。当前分支后续 clone 会包含 `08_media/models`，但 release 构建脚本仍会剔除整个 `08_media`。
- 385 项 Python、12 个 Node 测试、compileall、38 个 JavaScript、42 个 JSON、30 个 Shell、凭据扫描和 6 个 C/C++ 原生测试通过。
- 从 clone 生成 tar.gz 后检查 567 个归档条目，不含 `08_media`、`10_archive`、`.om`、私钥或非模板 `.env`；radar-only mock root 安装通过。
- 这不是 SS928 实板安装、systemd、reboot 或独立供电证据。
