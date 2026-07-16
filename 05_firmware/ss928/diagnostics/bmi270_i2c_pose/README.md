# SS928 BMI270 I2C 姿态读取

该 C 工程仅用于用户态 I2C、寄存器和姿态输出诊断，正式服务使用 `06_software/board_runtime/bmi270_backpack`。构建所需 Bosch 头文件不在仓库中：

```sh
make BMI270_CONFIG_INC=/opt/bosch/bmi270
```

接线以 `04_hardware/ss928/40pin-usage.md` 为唯一事实来源。

这个小工程走 `I2C0` 轮询读取 BMI270，板端输出 CSV，电脑端可以用串口工具看文本，也可以用 `viewer.html` 做可视化。

## 接线

优先接 3.3V，不要接 5V。BMI270 数据手册里芯片 VDD/VDDIO 最高 3.6V，SS928 40Pin 的 I2C 也是 3.3V 侧。

| BMI270 模块 | SS928 40Pin | 说明 |
| --- | --- | --- |
| VCC | Pin1 或 Pin17, VCC3V3 | 3.3V |
| GND | Pin6/9/14/20/25/30/34/39 任意一个 | 共地 |
| SDA | Pin3, `I2C0_SDA` | I2C 数据 |
| SCL | Pin5, `I2C0_SCL` | I2C 时钟 |
| CS | Pin1 或 Pin17, VCC3V3 | 拉高保持 I2C 模式 |
| SDO | GND | I2C 地址为 `0x68`；接 3.3V 则地址为 `0x69` |
| INT1 | Pin13, `GPIO2_1` | 可选，后续做数据就绪中断再用 |
| INT2 | 先不接 | 可选；需要第二路中断时可接到空闲 GPIO，例如 Pin15/`GPIO0_4` |

严格说除电源外有 6 个信号脚；第一版程序只需要 `SDA/SCL/CS/SDO`，`INT1/INT2` 都不是必须。你说的“另外 5 个”可以理解为先接 `SDA/SCL/SDO/CS/INT1`，`INT2` 留空。

## 板端引脚复用

如果系统启动后 40Pin 没有自动切到 I2C0，在板端执行：

```sh
cd /path/to/repo/05_firmware/ss928/diagnostics/bmi270_i2c_pose
sudo sh ./pinmux_i2c0.sh
```

脚本里关键两句是：

```sh
bspmm 0x102F013c 0x2031  # Pin3 -> I2C0_SDA
bspmm 0x102F0140 0x2031  # Pin5 -> I2C0_SCL
```

## 编译

在 SS928 的 Ubuntu 上：

```sh
cd /path/to/repo/05_firmware/ss928/diagnostics/bmi270_i2c_pose
make
```

如果在交叉编译环境里：

```sh
make CC=aarch64-mix210-linux-gcc
```

这个 Makefile 会直接引用补充资料里的 `BMI270_config.h`。如果你只把本目录单独拷到板子上，需要同时把 `补充资料/BMI270模块驱动例程/STM32(标准库)keil/Inc/BMI270_config.h` 拷过来，或修改 Makefile 里的 `BMI270_CONFIG_INC`。

## 运行

先看 I2C 设备名：

```sh
ls /dev/i2c-*
```

默认用 `/dev/i2c-0` 和地址 `0x68`：

```sh
sudo ./bmi270_i2c_pose --dev /dev/i2c-0 --addr 0x68 --rate 200
```

如果 `SDO` 接到了 3.3V，改成：

```sh
sudo ./bmi270_i2c_pose --dev /dev/i2c-0 --addr 0x69 --rate 200
```

输出格式：

```text
# pitch_deg,roll_deg,yaw_deg,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps,temp_c,t_ms
1.25,-0.43,12.80,0.01234,-0.00342,0.99812,0.100,-0.050,0.020,31.50,1234.5
```

## 电脑显示

最简单：用串口终端打开 SS928 的调试串口，在串口控制台里运行上面的程序，就能看到 CSV 文本。

可视化：用 Chrome 或 Edge 打开 `viewer.html`，点 `Connect Serial`，选择同一个串口。注意同一时间只能有一个程序占用 COM 口，打开网页前先关掉 SSCOM、MobaXterm、Xshell 之类的串口连接。

如果你是通过 SSH 运行板端程序，数据会走 SSH 终端，不会自动进浏览器串口可视化。要做网络可视化的话，下一步可以把板端 CSV 改成 WebSocket/UDP 输出。
