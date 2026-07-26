# SS928 板载温度

`temperature_reader.py` 读取内核模块提供的 `/proc/Tsensor`。输出始终包含
`status`：`ok`、`invalid` 或 `unavailable`。读取失败时不会返回伪造温度。

```sh
python3 temperature_reader.py
python3 temperature_reader.py --interval 5
```

正式 service 每 5 秒输出一行 JSON 到 journal。`/proc/Tsensor` 不存在时 service 会保持重启/记录 unavailable；它不是 `smartbag.target` 的硬依赖，不影响本地告警。

驱动源码位于 `05_firmware/ss928/tsensor`。必须使用与板端 `uname -r`、kernel config、交叉工具链完全匹配的内核树构建；仓库不提交 `.ko`，也不自动加载未知版本模块。
