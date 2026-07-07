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
- 按 `large_vehicle`、`small_rider`、`unknown_or_other` 使用不同提前预警时间窗和安全半径。
- 风险输出分为候选层 `raw_risk_level` 和实际显示/震动层 `display_risk_level`，保留多帧确认、防抖和降级迟滞。
- 输出 `warning_action` 震动动作：不震动、短弱震、间歇中等震动、强快速脉冲、高频连续强震。
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

当前风险模型不是“看到车就报警”，也不是只看无限直线轨迹或统一分数阈值。它会综合 CPA、佩戴者前方行走走廊、目标类别严重性、速度、当前距离、TTC/DRAC、track 年龄、速度置信度、位置抖动和观测质量。

### Future Conflict Gate / 未来冲突闸门

风险判定先检查目标未来有限时间内是否真的会接近佩戴者：

- `path_conflict=True` 只在目标会进入个人安全圆，或会进入前方有限行走走廊时成立。
- `moving_away=True` 且没有未来路径冲突时，候选风险会被强制压到 SAFE。
- 目标只是远处横向车流、侧边通过、或 CPA 最近距离仍大于安全半径和走廊阈值时，最多 ATTENTION，不允许 CAUTION/DANGER/EMERGENCY。
- `time_to_enter_corridor()` 使用有限矩形走廊 `|x| <= corridor_half_width`、`0 <= z <= corridor_depth`，不再把无限延长直线当作必然碰撞。
- 单帧 CPA/TTC 异常不会直接驱动震动输出；`display_risk_level` 仍然经过多帧确认、趋势一致性和观测质量检查。

预警等级语义：

```text
SAFE:      安全，不提醒，不震动。
ATTENTION: 需要注意，轻微提醒。
CAUTION:   有被碰到的可能，需要注意观察。
DANGER:    有可能发生较严重交通事故，需要拉开距离或主动躲避。
EMERGENCY: 高概率发生严重交通事故，一定要立刻躲避。
```

震动动作映射：

```text
SAFE:      none
ATTENTION: short_weak_pulse
CAUTION:   medium_interval_pulse
DANGER:    strong_fast_pulse
EMERGENCY: continuous_high_frequency
```

类别提前量：

```text
large_vehicle: car, truck, bus
  质量大、事故严重性高，候选预警更早。约 6s ATTENTION、4.8s CAUTION、3s DANGER、1.3s EMERGENCY。

small_rider: bicycle, motorcycle
  低速且不进入 PATH 时更克制。约 4s ATTENTION、3s CAUTION、2s DANGER、1s EMERGENCY。

unknown_or_other:
  使用中间配置。
```

风险输出分两层：

- `raw_risk_level`：根据 CPA、TTC、走廊、类别和速度算出的候选风险。大车可以更早进入 ATTENTION/CAUTION 候选。
- `display_risk_level`：实际画框颜色和后续震动模块应使用的风险等级，必须经过多帧确认、质量检查、降级迟滞和 fast path 限制。

误报抑制规则示例：

- 路边停着的摩托车、电动车、自行车，如果不在 PATH 内，通常 SAFE，最多 ATTENTION。
- 远处横向通过的车辆，如果 CPA 不进入佩戴者路径，通常 SAFE 或 ATTENTION，不应 CAUTION/DANGER。
- 大车即使当前属于 REMOTE，只要 CPA 显示数秒内会进入前方走廊或个人空间，也可以提前形成候选预警。
- 短 track、速度置信度低、位置抖动大、速度方向频繁反转时，显示风险最多 ATTENTION，除非目标已经非常近或危险状态连续稳定。
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
distance_trend_mps, approach_consistency, path_conflict_consistency
radial_closing_speed_mps, trajectory_distance_m
cpa_time_s, cpa_distance_m, cpa_valid
moving_away, approaching, path_conflict, will_enter_personal_space, will_enter_warning_corridor
personal_entry_time_s, corridor_entry_time_s, min_future_distance_m, conflict_reason
ttc_s, drac_mps2, motion_pattern, corridor_zone
severity_class, warning_action, warning_time_horizon_s, warning_radius_m
risk_action_reason, risk_cap_reason
raw_risk_score, raw_risk_level, display_risk_score, display_risk_level
stabilizer_pending_level, stabilizer_pending_count, stabilizer_required_frames, stabilizer_reason
trajectory_risk, ttc_risk, drac_risk, closing_risk
distance_confidence, observation_quality, quality_flags
```

排查顺序：先看 `raw_risk_level` 和 `display_risk_level` 是否分离；再看 `path_conflict`、`moving_away`、`will_enter_personal_space`、`will_enter_warning_corridor`、`personal_entry_time_s`、`corridor_entry_time_s` 和 `conflict_reason` 是否符合真实画面；然后看 `cpa_time_s`、`cpa_distance_m`、`corridor_zone`；再看 `risk_action_reason` 是不是大车提前预警、路径冲突或当前进入个人空间；再看 `risk_cap_reason` 是否为 `moving_away_no_future_conflict`、`no_corridor_entry`、`remote_traffic_no_path_conflict`、`unstable_single_frame_cpa`、`side_static`、`low_speed_non_path`、`unstable_track`；最后检查 `distance_trend_mps`、`approach_consistency`、`path_conflict_consistency`、`velocity_stability`、`position_jitter_m` 和 `velocity_confidence`。

判断修复是否有效：路边静止摩托/电动车不应 CAUTION；远处横向车流如果 `path_conflict=0` 不应 DANGER；正在远离的目标应出现 `moving_away=1` 和 `risk_cap_reason=moving_away_no_future_conflict`；大车真实进入路径时应提前形成候选 ATTENTION/CAUTION；真实进入正前方路径的自行车/电动车应出现 ATTENTION/CAUTION；单帧距离或速度跳变应出现 `unstable_single_frame_cpa` 或增加确认帧数，不应直接强震。
## Overlay 显示文字

`--overlay-verbosity` 控制检测框文字长度：

```text
minimal: 只显示类别、距离和风险等级。
normal:  默认值，显示 ID、类别、距离、速度、风险等级、CPA/TTC、zone。
debug:   显示 qD、qV、vx/vz、TRAJ、risk terms、severity、risk action、risk cap 等调试信息。
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
