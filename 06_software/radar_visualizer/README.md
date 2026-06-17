# PC 端毫米波雷达可视化测试工具

本工具用于电脑端初测 `MS60-3015S80M4-3V3-B-NLS-1T2R-S7136H` 60GHz 毫米波雷达模块。

当前功能：

- 读取雷达 UART 主动上报数据。
- 解析 `0x5A` 主动上报帧。
- 解析 `TYPE=0x07` BSD 目标列表。
- 显示最多 8 个目标的距离、角度、速度、目标 ID。
- 在 `±40°` 扇形视场内实时绘制目标位置和接近方向。
- 按距离和速度给出 `safe / low / medium / high / emergency` 风险等级。

## 资料依据

关键资料位置：

- `10_archive/ss928/补充资料/雷达模块.zip`
- `10_archive/ss928/补充资料/radar_tmp_extract/60GBSD汽车检测AT6010 SOC HCI Protocol_V1.4.pdf`
- `10_archive/ss928/补充资料/radar_tmp_extract/MS60-3015S80M4-3V3-B-NLS-1T2R-S7136H产品手册_v1.0_20250901.pdf`
- `10_archive/ss928/work/radar_uart_test/radar_uart_dump.c`

已确认参数：

- 工作电压：`3.3V`
- 通信接口：`UART`
- 默认波特率：`921600`
- 水平视角：`±40°`
- 刷新时间：`100ms`
- 最大目标数：`8`
- BSD 目标字段：距离、角度、速度、目标 ID

限制：

- 该模块是 BSD/RCW 汽车盲区预警类雷达，不是 360° 雷达。
- 资料说明当前版本主要支持接近预警，暂不支持远离目标探测。
- 静止障碍物、低速人体、非车辆目标的实际效果需要实测。

## 硬件接线

需要：

- 雷达模块
- USB-TTL 串口模块，必须支持 `3.3V TTL`
- 杜邦线

接线：

| 雷达模块 | USB-TTL |
| --- | --- |
| `3.3V` | `3.3V` |
| `GND` | `GND` |
| `TX` | `RX` |
| `RX` | `TX` |
| `OUT` | 暂不接 |

注意：

- 不要接 RS232。
- 不要用 5V 供电。
- `TX/RX` 需要交叉。
- 如果无数据，先检查 `TX/RX` 是否接反。

## 先用官方上位机验证

资料包中包含官方上位机：

```text
10_archive/ss928/补充资料/雷达模块/雷达模块/60GBSD汽车检测ATRearMonitorV0.2.4/ATRearMonitorV0.2.4/rearmonitor.exe
```

步骤：

1. 插入 USB-TTL。
2. 在 Windows 设备管理器中查看 COM 口，例如 `COM5`。
3. 打开官方上位机。
4. 设置串口为 `COM5`，波特率 `921600`。
5. 点击 ON/OFF 或开始测试。
6. 让人、车模、自行车从雷达前方接近，确认官方界面是否显示目标。

官方上位机能显示目标后，再运行本工具。

## 安装依赖

本工具 GUI 使用 Python 自带 `tkinter`，真实串口模式需要 `pyserial`。

```powershell
python -m pip install pyserial
```

如果只是看 demo，不需要安装 `pyserial`。

## 运行 demo

```powershell
cd D:\mywork\code\embedded-contest-project\06_software\radar_visualizer
python radar_visualizer.py --demo
```

demo 会生成模拟目标，用来检查图像界面和风险显示。

## 读取真实雷达

把 `COM5` 改成你的实际串口号：

```powershell
cd D:\mywork\code\embedded-contest-project\06_software\radar_visualizer
python radar_visualizer.py --port COM5
```

如果你想显示更远距离：

```powershell
python radar_visualizer.py --port COM5 --max-range 50
```

如果实测发现左右方向相反：

```powershell
python radar_visualizer.py --port COM5 --invert-angle
```

## 测试

```powershell
cd D:\mywork\code\embedded-contest-project
python -m unittest discover -s 06_software/radar_visualizer/tests -v
```

当前测试覆盖：

- 主动上报帧 `0x5A` 解析
- `TYPE=0x07` BSD 目标解析
- 噪声和坏 checksum 过滤
- 分包读取
- 左/中/右区域判断
- 风险等级判断
- 画布坐标换算

## 当前风险规则

```text
emergency: distance <= 1m
high     : distance <= 2m or velocity >= 2m/s
medium   : distance <= 4m or velocity >= 1m/s
low      : distance <= 8m
safe     : others
```

这里假设速度正值表示接近。若实测相反，需要修改 `risk.py` 或增加速度翻转参数。
