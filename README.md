# 基于 SS928 的智能背包项目

本仓库用于保存基于 SS928 的智能背包项目资料和代码。当前可运行、正在重点调试的软件部分是 PC 端视觉避障原型，目录为：

```text
06_software/vision_obstacle_tracker
```

当前阶段说明：风险判定主流程只采用视觉避障，不采用毫米波雷达参与当前 `vision_obstacle_tracker` 的风险决策。

## 当前功能

- 支持 USB 摄像头实时输入。
- 支持本地录制视频输入。
- 使用 Ultralytics YOLO 做目标检测。
- 使用 BoT-SORT 做目标跟踪。
- 额外实现稳定 ID 重关联，降低短时间 ID 跳变影响。
- 基于单目地面投影估计目标距离。
- 对每个目标估计横向/纵向速度和运动模式。
- 根据距离、速度、TTC、轨迹距离等信息计算风险分数。
- 在 OpenCV 窗口中绘制检测框、目标 ID、距离、速度、风险等级等信息。
- 支持 ROI 裁剪，减少天空、建筑上半部分等无效区域进入 YOLO。
- 支持 YOLO 类别前置过滤，减少无关类别进入后处理和 tracker。
- 支持优先加载已有 OpenVINO 导出模型，用于 CPU 推理优化。
- 支持运行时性能剖析，用于查看耗时主要发生在哪个阶段。
- 支持导出风险 CSV 日志，用于逐帧分析误报、漏报和颜色稳定逻辑。

## 目录结构

```text
00_admin/        项目管理、计划、日志、会议记录
01_requirements/ 需求分析、赛题解读、评分点和约束
02_research/     资料调研、参考方案、模块资料
03_design/       系统设计、架构、接口、流程图
04_hardware/     硬件设计、原理图、PCB、BOM、接线
05_firmware/     嵌入式固件相关内容
06_software/     PC 端软件、算法原型和工具脚本
07_tests/        测试方案、测试记录、验证资料
08_media/        本地图片和视频素材，不上传 GitHub
09_deliverables/ 论文、答辩 PPT、演示材料、最终提交包
10_archive/      旧版本、废弃方案、历史归档，不上传 GitHub
```

以下内容按当前规则不上传 GitHub：

```text
08_media/
10_archive/
*.mp4、*.avi、*.mov、*.mkv 等视频文件
risk_log.csv
*_risk_log.csv
本地构建产物
本地下载的第三方依赖目录
```

## 安装视觉避障程序

进入视觉避障目录：

```powershell
cd D:\mywork\code\embedded-contest-project\06_software\vision_obstacle_tracker
```

安装 Python 依赖：

```powershell
py -m pip install -r requirements.txt
```

可选依赖：

```powershell
py -m pip install openvino
py -m pip install PyYAML
```

说明：

- `openvino` 用于 CPU 推理优化。
- `PyYAML` 用于更完整地读取 YAML 标定文件。
- 第一次运行 YOLO 时，如果本地没有权重文件，程序可能会自动下载模型权重。

## 读取视频进行检测

基础视频检测命令：

```powershell
cd D:\mywork\code\embedded-contest-project\06_software\vision_obstacle_tracker
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4
```

推荐的 CPU 演示命令：

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --profile
```

如果已经导出过 OpenVINO 模型，推荐这样运行：

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --prefer-openvino --profile
```

保存带检测框和风险信息的视频：

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --save-output D:\path\overlay.mp4
```

不打开窗口，逐帧处理完整视频并保存结果：

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --video-every-frame --no-display --save-output D:\path\overlay_full.mp4
```

短视频自动测试，只处理前 300 帧：

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --max-frames 300 --no-display --profile
```

## 实时开启摄像头检测

基础摄像头检测命令：

```powershell
cd D:\mywork\code\embedded-contest-project\06_software\vision_obstacle_tracker
py vision_obstacle_tracker.py --source camera
```

推荐的 CPU 摄像头测试命令：

```powershell
py vision_obstacle_tracker.py --source camera --runtime-profile cpu_demo --roi-top-ratio 0.20 --profile
```

如果打开了错误摄像头，尝试修改摄像头编号：

```powershell
py vision_obstacle_tracker.py --source camera --camera-index 0
py vision_obstacle_tracker.py --source camera --camera-index 1
```

如果默认 FFmpeg 摄像头后端无法打开，可以切换 OpenCV 后端：

```powershell
py vision_obstacle_tracker.py --source camera --camera-backend opencv --camera-index 1
```

## OpenVINO CPU 推理优化

第一次需要显式导出 OpenVINO 模型：

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --export-openvino
```

导出完成后，后续运行可以优先加载已有 OpenVINO 模型：

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --prefer-openvino --profile
```

注意：

- `--prefer-openvino` 只会优先加载已经存在的 OpenVINO 导出目录。
- 如果 `.pt` 权重旁边没有对应的 OpenVINO 模型目录，程序会回退加载原始 PyTorch 模型。
- `--prefer-openvino` 不会自动导出模型；自动导出只在显式传入 `--export-openvino` 时发生。

## 风险日志调试

导出逐帧风险诊断 CSV：

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --prefer-openvino --risk-log-csv D:\path\risk_log.csv --profile
```

常用字段：

```text
track_id, class_name, distance_m, velocity_x_mps, velocity_z_mps,
radial_closing_speed_mps, trajectory_distance_m, ttc_s, drac_mps2,
motion_pattern, raw_risk_score, raw_risk_level,
display_risk_score, display_risk_level,
trajectory_risk, ttc_risk, drac_risk, closing_risk,
distance_confidence, velocity_confidence, observation_quality,
quality_flags, stabilizer_reason
```

排查误报或颜色不符合预期时，建议按这个顺序看：

1. 先看 `raw_risk_score` 和 `raw_risk_level`，判断原始风险计算是否已经偏高或偏低。
2. 再看 `display_risk_level`，判断是不是显示层稳定器导致颜色延迟或降级。
3. 查看 `stabilizer_reason`，确认是否因为观测质量、连续帧确认或降级保持导致当前颜色。
4. 查看 `trajectory_distance_m`、`ttc_s`、`motion_pattern`，判断是轨迹风险、TTC 风险还是近距离静态障碍触发。
5. 查看 `distance_confidence`、`velocity_confidence`、`quality_flags`，判断距离或速度是否受检测框、地面投影、相机抖动影响。

## 性能剖析和调试

开启 profile：

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --profile
```

终端会周期性输出滑动平均耗时，主要字段包括：

```text
capture        取帧耗时
roi/crop       ROI 裁剪耗时
enhance        图像增强耗时
ego-motion     相机自运动估计耗时
infer+track    YOLO 推理和 BoT-SORT 跟踪耗时
postprocess    检测结果转换、类别过滤、坐标还原耗时
risk           测距、速度估计和风险计算耗时
draw           overlay 绘制耗时
display/write  窗口显示和视频写入耗时
total          单帧总耗时
```

常见瓶颈判断：

- `infer+track` 高：优先降低 `--imgsz`，使用 `--runtime-profile cpu_demo`，尝试 `--roi-top-ratio 0.15` 或 `0.20`，导出后再尝试 `--prefer-openvino`。
- `display/write` 高：对比 `--display-every-n 5` 和 `--no-display`。
- `draw` 高：通常是检测框、文字和 overlay 绘制较多。
- `ego-motion` 高：对比 `--ego-motion-mode off`，或者调大 `--ego-motion-every-n`。
- 摄像头 FPS 很低：检查光照、曝光、摄像头后端、分辨率和驱动设置。暗光下自动曝光可能会把摄像头实际帧率压得很低。

建议对比命令：

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --display-every-n 1 --profile
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --display-every-n 5 --profile
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --no-display --profile
```

预期结果：

```text
--no-display 通常最快。
--display-every-n 5 只降低 OpenCV 窗口刷新频率，不降低 YOLO 检测、跟踪、测距和风险计算频率。
--display-every-n 1 保持默认每帧刷新窗口的行为。
```

## 常用参数说明

```text
--source camera|video
    选择摄像头输入或视频文件输入。

--video D:\path\input.mp4
    指定视频文件路径，只在 --source video 时使用。

--runtime-profile realtime|cpu_demo|balanced|quality
    选择运行预设，影响采集分辨率、YOLO 输入尺寸、置信度阈值和最大检测数。

--roi-top-ratio 0.20
    推理前裁掉图像顶部 20%。用于减少天空、天花板、建筑上半部分等无效区域。
    建议从 0.15 或 0.20 开始试，过大可能漏掉远处刚出现的目标。

--target-classes car,bicycle,motorcycle,bus,truck
    指定保留的目标类别。设置为 all 时保留 YOLO 的所有类别。

--prefer-openvino
    如果 .pt 权重旁边已有 OpenVINO 导出目录，则优先加载 OpenVINO 模型。

--export-openvino
    将 YOLO 模型导出为 OpenVINO 格式。

--display-every-n 5
    每 N 个处理帧刷新一次 OpenCV 窗口。
    这个参数只降低窗口刷新频率，不跳过检测、跟踪、测距和风险判定。

--no-display
    不打开 OpenCV 预览窗口。

--save-output D:\path\overlay.mp4
    保存带检测框和风险信息的视频。

--risk-log-csv D:\path\risk_log.csv
    保存风险判定和中间计算结果，便于逐帧分析。

--max-frames 300
    处理指定帧数后自动退出，适合短测试。

--profile
    周期性输出各阶段耗时，用于定位性能瓶颈。
```

更完整的视觉避障说明见：

```text
06_software/vision_obstacle_tracker/README.md
```

## 测试

运行视觉避障单元测试：

```powershell
cd D:\mywork\code\embedded-contest-project\06_software\vision_obstacle_tracker
py -m unittest discover -s tests -v
```

检查 Python 文件是否能编译：

```powershell
cd D:\mywork\code\embedded-contest-project\06_software\vision_obstacle_tracker
py -m compileall .
```

## 更新和 GitHub 记录规则

以后每次有实质更新，都要同步更新 GitHub 可见文档：

1. 如果命令、参数、运行方式或调试方法变化，更新对应模块的 README。
2. 如果项目主页、快速开始、整体说明或调试流程变化，更新根目录 `README.md`。
3. 每次上传一组改动前，在 `CHANGELOG.md` 增加日期和更新内容。
4. 不上传测试视频、生成的风险日志、archive、本地构建产物和大体积第三方依赖目录。

这样做的目的是让 GitHub 项目主页不仅保存代码，也能直接说明当前项目怎么运行、怎么调试、最近改了什么。
