# 基于 SS928 的智能背包项目

本仓库用于保存基于 SS928 的智能背包项目资料和代码。当前可运行、正在重点调试的软件部分是 PC 端纯视觉避障原型：

```text
06_software/vision_obstacle_tracker
```

当前阶段说明：`vision_obstacle_tracker` 的风险判定主流程只使用视觉，不使用毫米波雷达参与决策。

## 当前功能

- 支持 USB 摄像头实时检测。
- 支持本地录制视频检测。
- 使用 Ultralytics YOLO 做目标检测，使用 BoT-SORT 做目标跟踪。
- 使用稳定 ID 重关联降低短时间 ID 跳变影响。
- 基于单目地面投影和目标尺寸融合估计距离。
- 使用鲁棒短历史速度估计，降低 bbox 抖动造成的虚假高速。
- 使用 CPA（未来最近接近点）和佩戴者前方走廊判断真实风险。
- 使用风险上限机制限制远处横向交通流、路边静止目标、短 track 和速度不稳定目标的误报。
- 支持 ROI 顶部裁剪、YOLO 类别前置过滤、OpenVINO CPU 推理、ego-motion、risk CSV、display-every-n、cpu_demo profile。
- 支持 `--overlay-verbosity minimal|normal|debug` 控制画面文字详细程度。

## 目录结构

```text
00_admin/         项目管理、计划、日志、会议记录
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

不上传 GitHub 的内容：`08_media/`、`10_archive/`、视频文件、生成的 risk log、本地构建产物和大体积第三方依赖目录。

## 安装视觉避障程序

```powershell
cd D:\mywork\code\embedded-contest-project\06_software\vision_obstacle_tracker
py -m pip install -r requirements.txt
```

可选依赖：

```powershell
py -m pip install openvino
py -m pip install PyYAML
```

`openvino` 用于 CPU 推理优化；`PyYAML` 用于更完整地读取 YAML 标定文件。第一次运行 YOLO 时，如果本地没有权重文件，程序可能会自动下载模型权重。

## 读取视频进行检测

基础视频检测：

```powershell
cd D:\mywork\code\embedded-contest-project\06_software\vision_obstacle_tracker
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4
```

推荐 CPU 演示命令：

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --profile
```

如果已经导出过 OpenVINO 模型：

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --prefer-openvino --profile
```

保存带检测框和风险信息的视频：

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --save-output D:\path\overlay.mp4
```

不打开窗口，逐帧处理完整视频并保存：

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --video-every-frame --no-display --save-output D:\path\overlay_full.mp4
```

## 实时开启摄像头检测

基础摄像头检测：

```powershell
cd D:\mywork\code\embedded-contest-project\06_software\vision_obstacle_tracker
py vision_obstacle_tracker.py --source camera
```

推荐 CPU 摄像头测试：

```powershell
py vision_obstacle_tracker.py --source camera --runtime-profile cpu_demo --roi-top-ratio 0.20 --profile
```

如果打开了错误摄像头，修改摄像头编号：

```powershell
py vision_obstacle_tracker.py --source camera --camera-index 0
py vision_obstacle_tracker.py --source camera --camera-index 1
```

如果默认 FFmpeg 摄像头后端无法打开，切换 OpenCV 后端：

```powershell
py vision_obstacle_tracker.py --source camera --camera-backend opencv --camera-index 1
```

## OpenVINO CPU 推理优化

第一次显式导出 OpenVINO 模型：

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --export-openvino
```

后续运行优先加载已有 OpenVINO 模型：

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --prefer-openvino --profile
```

`--prefer-openvino` 只会优先加载已经存在的 OpenVINO 导出目录；如果不存在，会回退加载原始 PyTorch 模型。

## 风险判定语义

当前风险模型不是“看到车就报警”，也不是只看无限直线轨迹。它会综合个人安全半径、未来最近接近时间 `cpa_time_s`、未来最近接近距离 `cpa_distance_m`、佩戴者前方行走走廊 `corridor_zone`、TTC、DRAC、径向接近速度、目标类别、速度、track 年龄和速度稳定性。

风险语义：

```text
SAFE:      远处交通流、路边静止物体、远离目标，或 CPA 不进入安全区域。
ATTENTION: 近侧或可能接近的目标，需要注意，但当前不是马上碰撞。
CAUTION:   数秒内可能进入佩戴者前方路径或个人安全半径。
DANGER:    1 到 2 秒内高度可能碰撞，或高速车辆进入正前方路径。
EMERGENCY: 极短 TTC、极小 CPA 距离，或当前距离已经小于个人安全半径。
```

走廊区域：

```text
PATH        正前方行走路径
SIDE        近侧区域
REMOTE      远处或侧向交通区域
SIDE_STATIC 路边静止或低速目标
UNK         无法判断
```

误报抑制规则示例：

- 路边停着的摩托车、电动车、自行车，如果不在 PATH 内，通常 SAFE，最多 ATTENTION。
- 远处横向通过的车辆，如果 CPA 不在短时间内进入个人安全半径，不应 CAUTION/DANGER。
- 短 track、速度置信度低、位置抖动大、速度方向频繁反转时，风险最多 ATTENTION，除非目标已经非常近。
- 真正进入正前方路径的自行车、电动车或车辆仍会触发 ATTENTION/CAUTION/DANGER。

## 风险日志调试

推荐命令：

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --prefer-openvino --overlay-verbosity debug --risk-log-csv D:\path\risk_log.csv --profile
```

重点字段：

```text
track_id, class_name, distance_m, x_m, z_m, vx_mps, vz_mps, speed_mps
velocity_confidence, velocity_stability, position_jitter_m
radial_closing_speed_mps, trajectory_distance_m
cpa_time_s, cpa_distance_m, cpa_valid
ttc_s, drac_mps2, motion_pattern, corridor_zone, risk_cap_reason
raw_risk_score, raw_risk_level, display_risk_score, display_risk_level
trajectory_risk, ttc_risk, drac_risk, closing_risk
distance_confidence, observation_quality, quality_flags, stabilizer_reason
```

排查顺序：先看 raw/display 风险；再看 `cpa_time_s`、`cpa_distance_m`、`corridor_zone`；然后看 `risk_cap_reason` 是否为 `remote_traffic`、`side_static`、`low_speed_non_path`、`unstable_track`；最后检查 `velocity_stability`、`position_jitter_m` 和 `velocity_confidence`。

判断本轮误报修复是否有效：路边静止摩托/电动车不应 CAUTION；远处横向车流不应 DANGER；真实进入正前方路径的自行车/电动车应出现 ATTENTION/CAUTION；risk log 应包含 CPA、corridor zone 和 risk cap 字段。

## Overlay 显示文字

`--overlay-verbosity` 控制检测框文字长度：

```text
minimal: 只显示类别、距离和风险等级。
normal:  默认值，显示 ID、类别、距离、速度、风险等级、CPA/TTC、zone。
debug:   显示 qD、qV、vx/vz、TRAJ、risk terms、risk cap 等调试信息。
```

示例：

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --overlay-verbosity minimal
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --overlay-verbosity debug --risk-log-csv D:\path\risk_log.csv
```

## 性能剖析和调试

开启 profile：

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --profile
```

常用对比命令：

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --display-every-n 1 --profile
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --display-every-n 5 --profile
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --no-display --profile
```

`--no-display` 通常最快；`--display-every-n 5` 只降低 OpenCV 窗口刷新频率，不降低 YOLO 检测、跟踪、测距和风险计算频率。

## 常用参数

```text
--source camera|video                 选择摄像头输入或视频文件输入。
--video D:\path\input.mp4          指定视频文件路径。
--runtime-profile cpu_demo            推荐 CPU 演示预设。
--roi-top-ratio 0.20                  推理前裁掉图像顶部 20%。
--target-classes car,bicycle,...      指定保留的目标类别，all 表示全部类别。
--prefer-openvino                     优先加载已有 OpenVINO 导出模型。
--export-openvino                     将 YOLO 模型导出为 OpenVINO。
--display-every-n 5                   每 N 个处理帧刷新一次窗口。
--overlay-verbosity minimal|normal|debug 控制检测框文字详细程度。
--no-display                          不打开 OpenCV 预览窗口。
--save-output D:\path\overlay.mp4   保存带检测框和风险信息的视频。
--risk-log-csv D:\path\risk_log.csv 保存风险判定和中间计算结果。
--max-frames 300                      处理指定帧数后自动退出。
--profile                             周期性输出各阶段耗时。
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

1. 命令、参数、运行方式或调试方法变化时，更新对应模块 README。
2. 项目主页、快速开始、整体说明或调试流程变化时，更新根目录 `README.md`。
3. 每次上传一组改动前，在 `CHANGELOG.md` 增加日期和更新内容。
4. 不上传测试视频、生成的风险日志、archive、本地构建产物和大体积第三方依赖目录。

这样 GitHub 项目主页可以直接说明当前项目怎么运行、怎么调试、最近改了什么。
