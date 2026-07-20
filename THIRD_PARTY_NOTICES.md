# 第三方来源与许可说明

本轮行为参考来源为 `sanda-tt/ss928@970351c84a12f3219e7910ee488ac5ff579d6f98`。来源仓库根目录未发现可确认覆盖全部代码的 LICENSE，因此本项目没有原样复制其运行时代码，而是根据公开接口行为重实现，并在 `00_admin/sanda-upstream-import-manifest.json` 记录来源路径、blob SHA、作者来源、迁移决定和许可状态。

MR20 厂商 PDF、板卡 SDK/Sample、模型、镜像、RAR/ZIP、DXF/BRD、已编译二进制和 LFS 对象没有进入本仓库。它们只在研究文档中登记文件名和可验证结论；许可不明确的内容不得对外宣称可自由分发。

`wx-server-sdk` 由部署 CloudBase 云函数时按 `cloudfunctions/smartbag-api/package.json` 安装，适用其自身许可。Ultralytics、OpenCV、BlueZ、Python 包和板卡系统组件不随仓库重新分发，使用者需分别遵守其许可。模型、Cloud secret、设备凭据和本地配置不进入 Git。
