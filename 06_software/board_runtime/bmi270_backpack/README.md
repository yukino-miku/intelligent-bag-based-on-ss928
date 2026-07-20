# BMI270 背包姿态与运动趋势

支持 Linux IIO、用户态 I2C、probe/list-iio、roll/pitch/yaw、短时运动趋势、可调阈值、模拟输入、校准采集和跌倒桥接。六轴积分速度存在漂移，只能作短时趋势，不能当可靠绝对速度。

接线：I2C0 Pin3/Pin5，地址 `0x68`/`0x69`，详见 `04_hardware/ss928/40pin-usage.md`。用户态 I2C 初始化依赖合法来源的 Bosch `bmi270_config.bin`，本仓库不分发；优先验证内核 IIO。

```sh
cd /root/smartbag/imu
python3 bmi270_backpack.py --list-iio
python3 bmi270_backpack.py --probe-i2c --hardware-profile /etc/smartbag/hardware.json
python3 bmi270_backpack.py --simulate --no-ble
python3 bmi270_backpack.py --config config.example.json --hardware-profile /etc/smartbag/hardware.json --command-stdin --no-ble
```

`--hardware-profile` 使 Rev2 每笔 BMI270 用户态 I2C 事务使用 TCA9548A CH0 和统一跨进程锁；切换到 `legacy_pwm_haptics` 后会自动恢复 direct-I2C，不需要维护第二份 BMI 配置。

默认 `ble_enabled=false`。统一部署由 controller 注册 `SS928-SmartBag`，IMU 接收 `STATUS`、`ZERO`、`ZERO_V`、`SET key=value`；对外命名空间为 `IMU ...`。`fall_bridge.py` 直接把 BMI 样本转换为 fall detector 的 `ImuSample`，产生独立跌倒/撞击事件，不映射成交通风险等级。
