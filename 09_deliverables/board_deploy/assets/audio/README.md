# 提示音资产

L1-L4、R1-R4 和 `bad` 均是项目脚本生成的短正弦提示音，不包含第三方录音。
可使用以下命令重新生成：

```bash
python3 06_software/tools/audio_prepare/generate_alert_tones.py
```

音频默认关闭，不会阻塞震动控制。许可说明见根目录 `AUDIO_LICENSES.md`。
