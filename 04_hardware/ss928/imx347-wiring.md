# IMX347 接入

- 板卡/底板：EULER_4SEN V1.0。
- 传感器：sensor0，SONY IMX347，2 lane MIPI，I2C7。
- 数据链：VI -> VPSS -> VO -> MIPI；预览样例位于 `05_firmware/ss928/board_samples/imx347_mipi_preview`。
- sensor 时钟相关寄存器由样例启动流程配置，禁止把扩展口接线表中的 I2C0 当成 sensor0 I2C。

真实板卡运行前需确认当前 SDK 的 sensor 驱动、lane divide mode 和 EULER_4SEN 排线方向一致。
