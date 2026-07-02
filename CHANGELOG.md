# 更新记录

本文件记录已经上传到 GitHub 的项目更新。以后每次有实质功能、参数、文档或调试流程变化，都要在提交前增加对应记录。

## 2026-07-02

- 优化纯视觉避障风险判定，新增 CPA（未来最近接近点）指标：`cpa_time_s`、`cpa_distance_m`、`cpa_valid`。
- 新增佩戴者前方走廊分区：`PATH`、`SIDE`、`REMOTE`、`SIDE_STATIC`、`UNK`，并写入 risk CSV。
- 新增风险上限机制 `risk_cap_reason`，用于限制远处横向交通流、路边静止目标、低速非路径目标、短 track 和速度不稳定目标的误报。
- 改进 `TrackState` 速度估计，使用鲁棒短历史速度，新增 `velocity_stability` 和 `position_jitter_m`，降低 bbox/单目测距跳变造成的虚假 CUTIN。
- 新增 `--overlay-verbosity minimal|normal|debug`，默认 `normal` 缩短画面标签，`debug` 才显示完整风险调试信息。
- 更新 `06_software/vision_obstacle_tracker/README.md`，新增真实场景风险语义、CPA/走廊/risk cap 调试说明和推荐命令。
- 更新根目录 `README.md`，让 GitHub 项目主页同步说明本轮风险误报修复、risk log 字段和 overlay 调试方法。
- 补充测试覆盖路边静止摩托、慢速侧边自行车、横切进入个人空间的自行车、远处横向车流、正前方快速接近汽车、短 track/速度抖动目标、CSV 字段和 overlay 参数。
- 保留既有 ROI、YOLO 类别前置过滤、OpenVINO 优先加载、camera calibration、pitch 调节、ego-motion、risk CSV、display-every-n、cpu_demo profile 等功能。

## 2026-07-02 之前

- 将根目录 GitHub 项目主页 `README.md` 改为中文说明，并补充安装、视频检测、摄像头实时检测、OpenVINO、风险日志、保存视频、性能剖析和调试方法。
- 新增 `CHANGELOG.md`，用于记录每次上传到 GitHub 的更新内容。
- 明确以后每次功能更新都要同步更新相关 README 和本更新记录。
- 明确 `08_media/`、`10_archive/`、视频文件、生成的风险日志、本地构建产物和大体积第三方依赖目录不上传 GitHub。
- 近期视觉避障性能优化包括：YOLO 类别前置过滤、`--roi-top-ratio` ROI 顶部裁剪、`--prefer-openvino` 优先加载 OpenVINO、`--profile` 性能剖析、`--display-every-n` 窗口刷新降频。
- 近期视觉风险调试优化包括：风险 CSV 日志、运行预设、相机自运动质量记录、显示层风险稳定器、距离质量标志、风险分项诊断。
