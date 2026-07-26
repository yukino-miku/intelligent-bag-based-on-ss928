# 板载温度

温度运行时读取内核驱动导出的 `/proc/Tsensor` 三通道数据。驱动源代码位于 `05_firmware/ss928/tsensor`，需要针对实际 SS928 内核和工具链编译、加载。

读取失败会输出 `status=unavailable`，格式异常会输出 `status=invalid`；系统不会用固定数字伪造温度。温度服务只记录状态，不参与交通风险等级。
