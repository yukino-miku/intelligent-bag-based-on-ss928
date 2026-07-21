# YOLO11 ONNX to SS928 OM

本目录只负责模型转换，不包含模型权重或生成的 `.onnx`/`.om`。这些大文件继续放在 Git 忽略的 `08_media/` 或板端 `/root/smartbag/models/`。

## 固定契约

当前 `Ss928OmBackend` 要求：

- ONNX 输入：`images`，FP32，`1x3x640x640`；
- ONNX/OM 输出：FP32，`1x84x8400`，COCO 80 类 YOLO11 detect head；
- 目标 SoC：`SS928V100`；
- ATC：`framework=5`、`compile_mode=6`；
- AIPP：`RGB_PLANAR`、RGB、静态 `1/255` 归一化。

不能把 1024 模型的 shape 元数据直接改成 640。YOLO11 检测头内部网格也必须按 640 重新导出，否则 ONNX Runtime 和 ATC 会出现维度冲突。

## 1. 正确导出 640 ONNX

在安装 Ultralytics 的 PC 环境执行：

```sh
python3 - <<'PY'
from ultralytics import YOLO

YOLO("yolo11n.pt").export(
    format="onnx",
    imgsz=640,
    opset=13,
    dynamic=False,
    simplify=False,
)
PY
```

检查契约：

```sh
python3 inspect_onnx_contract.py /path/to/yolo11n.onnx
```

## 2. 准备量化校准图片

优先使用 20 张以上与背包摄像头场景相近、内容不同的 JPEG。不要使用全黑帧、重复帧或带密码/IP 的私有截图。

```sh
python3 prepare_calibration_list.py \
  /path/to/calibration-jpegs \
  /path/to/image_ref_list.txt \
  --count 20
```

## 3. 安装并加载官方转换工具

转换在 Linux x86_64 主机运行，不在 Windows、SS928 ARM 板或 OpenVINO 中运行。使用与当前板端镜像配套的官方 `SVP_NNN_PC`/CANN 工具；本次验证使用 `SVP_NNN_PC_V1.0.6.0`。安装后加载环境，例如：

```sh
set +u
source "$HOME/Ascend/ascend-toolkit/svp_latest/x86_64-linux/script/setenv.sh"
set -u
atc --version
```

工具包和 SDK 的许可需要单独确认，仓库不重新分发它们。

## 4. 转换

```sh
sh convert_yolo11_ss928.sh \
  /path/to/yolo11n_640.onnx \
  /path/to/image_ref_list.txt \
  /path/to/output/yolo11n_ss928
```

脚本会先执行 ONNX checker 和 shape/type 检查，再生成：

- `yolo11n_ss928.om`
- `yolo11n_ss928.atc.log`
- `yolo11n_ss928.sha256`

ATC 可能对官方配置中的 `aipp_mode` 打印兼容性 warning；必须继续检查日志中已经读取 `RGB_PLANAR`、三个 `var_reci_chn_*`，且网络解析、量化、tiling、指令和二进制生成全部结束。

## 5. 板端验证

先上传为新文件名，不覆盖当前已验证模型：

```sh
scp yolo11n_ss928.om root@BOARD_IP:/root/smartbag/models/yolo11n_ss928.om
sha256sum /root/smartbag/models/yolo11n_ss928.om
```

然后用 `--detector-backend ss928_om --model /root/smartbag/models/yolo11n_ss928.om` 启动短测。至少核对 ACL 输入/输出元数据、单帧 NPU 执行、实际目标命中、overlay，以及 30 分钟稳定性；ATC 成功不等于实板验收通过。

## 本次已生成候选模型

2026-07-21 使用同一官方 YOLO11n 权重正确重导出并转换：

- PT SHA256：`0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1`
- 640 ONNX SHA256：`aa916c427ea520e2e4db5a61e9074e1570715c655302895db4f575500ab51116`
- SS928 OM SHA256：`9e3c448ab7309428ea78cfdc509926404220fa74dd56c89e4995366f5f16af95`
- OM 大小：`3426459` bytes

本地产物位于 `08_media/models/ss928_yolo11n/`，不会进入 Git。当前电脑以太网未连接，因此该候选 OM 尚未完成实板 ACL 验证，部署默认值仍保持原 `yolov8n.om`。
