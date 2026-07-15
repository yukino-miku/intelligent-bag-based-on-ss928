# BMI270 接线

接线以 [40pin-usage.md](40pin-usage.md) 为准：Pin3 为 I2C0_SDA，Pin5 为 I2C0_SCL。VCC 接 3.3V，GND 共地，CSB 拉高进入 I2C 模式；SDO 接地为 `0x68`，接 3.3V 为 `0x69`。INT1/INT2 在轮询版本中可不接。

先执行 `i2cdetect -y 0`，再使用 `bmi270_backpack.py --probe-i2c --i2c-bus 0`。用户态初始化需要有合法来源的 Bosch `bmi270_config.bin`；仓库未分发该二进制。
