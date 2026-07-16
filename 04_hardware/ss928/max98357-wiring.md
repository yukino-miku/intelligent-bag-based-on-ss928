# MAX98357 接线

使用 Pin12/I2S_BCLK、Pin38/I2S_WS、Pin40/I2S_SD_TX，具体 pinmux 见 [40pin-usage.md](40pin-usage.md)。MAX98357 不需要 MCLK。功放与扬声器使用独立、满足峰值电流的电源，控制侧与 SS928 共地。音频是可选提醒，默认关闭，不能阻塞震动控制。
