# 双 MR20 以太网雷达

MR20 不占用 40Pin。左右雷达使用独立 IP、UDP 端口和 `side` 配置，由同一个 alert controller 启动两个 worker。默认 profile 关闭雷达；接入后编辑 `/etc/smartbag/mr20.json` 并启用 `config.json` 的 `radar.enabled`。

必须在实板确认雷达供电、网口拓扑、板端绑定地址、右后/左后设备 IP 和端口。worker 会校验来源 IP，并按 `source=radar:<name>` 与视觉事件融合；清除单个雷达源不会清除同侧视觉风险。
