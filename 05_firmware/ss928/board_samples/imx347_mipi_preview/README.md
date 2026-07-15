# IMX347 sensor0 MIPI preview

本目录只保留源码，不包含厂商 SDK/MPP 或构建产物。构建根目录不得写死个人路径：

```sh
make MPP_SAMPLE_ROOT=/opt/ss928/mpp/sample
```

目标为 EULER_4SEN V1.0、sensor0、IMX347 2lane、I2C7，实际宏、驱动和 lane mode 需与板端 SDK 版本核对。

This sample shows the live IMX347 stream from `sensor0` on the SDK 800x1280 MIPI display path.

Target hardware:

- MIPI display: `800x1280`
- Sensor adapter: `EULER_4SEN V1.0`
- Camera connection: only `sensor0` is connected
- Sensor mode: IMX347 `2lane`
- Sensor bus: `sensor0/I2C7`

It does not modify the original SDK. The media path is:

```text
IMX347(sensor0) -> VI -> VPSS -> VO -> MIPI TX
```

The preview path follows the SDK `src/vio/sample_vio.c` four-sensor EULER_4SEN mode for 2lane sensors:
`OT_VI_OFFLINE_VPSS_ONLINE`, but starts only sensor0.

The 1920x1080 camera image is scaled by VPSS to 1280x720, rotated 90 degrees by VO, and centered as 720x1280 on the 800x1280 panel.
This keeps the full camera frame visible while using most of the portrait display.

## Build

From this folder:

```sh
make
```

The default `MPP_SAMPLE_ROOT` is the local no-space SDK copy under this workspace:

```text
../../在线仓库/SS928V100_SDK_V2.0.2.2_MPP_Sample-master
```

If your MPP sample path is different:

```sh
make MPP_SAMPLE_ROOT=/path/to/SS928V100_SDK_V2.0.2.2_MPP_Sample-master
```

The default sensor type in this sample is:

```text
SONY_IMX347_2L_SLAVE_MIPI_2M_30FPS_12BIT
```

The sample also defaults to:

```text
SENSOR0_I2C_BUS=7
SENSOR0_LANE_DIVIDE_MODE=LANE_DIVIDE_MODE_3
```

## Run On Board

Before running, configure the IMX347 sensor0 clock to 37.125 MHz. The SDK README lists the register value as `0x8001`:

```sh
bspmm 0x11018440 0x8001
```

Then load the MPP drivers as usual for your current system image, copy the built binary to the board, and run:

```sh
./imx347_mipi_preview
```

Press Enter or Ctrl+C to stop.

This program uses the SDK's existing `800x1280` MIPI panel initialization table.

## Expected Log

The program prints the sensor and display layout before entering the preview loop:

```text
sensor0 config: vi_dev=0 vi_pipe=0 vi_chn=0 i2c=7 clk=0 rst=0 lane_divide=3
sensor input size: 1920x1080, display path: VI -> VPSS -> VO -> MIPI TX
display layout: rotate=1 vpss_out=1280x720 vo_rect={40,0,720,1280}
```

If VO rotation is not supported by the current firmware/MPP build, the program exits with `set vo rotation failed`.
