# 四路震动模块接线

左侧两路使用 Pin7/PWM10、Pin32/PWM1，右侧两路使用 Pin35/PWM14、Pin37/PWM15，唯一 pinmux 定义见 [40pin-usage.md](40pin-usage.md)。GPIO/PWM 只连接驱动模块控制输入；电机应由外部驱动和独立电源供电，并与板卡共地。系统启动、退出、异常和 detector 超时均必须把四路占空比归零。
