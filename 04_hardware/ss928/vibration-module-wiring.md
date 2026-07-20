# 四路震动模块接线

Rev2 使用 TCA9548A CH1/CH2 上的左右 TM6605 驱动 LRA；Pin7/Pin32 改为左右灯光 PWM。旧的四路 PWM 振动接线只属于 `legacy_pwm_haptics` 回滚 profile。唯一引脚定义见 [40pin-usage.md](40pin-usage.md)。LRA 和电机不得直连 GPIO，驱动与负载使用独立合规电源并和板卡共地。系统启动、退出、异常和来源超时必须清除对应输出。
