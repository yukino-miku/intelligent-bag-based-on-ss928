# Vision Obstacle Tracker

PC-side prototype for USB-camera or recorded-video testing:

- YOLO object detection
- BoT-SORT object tracking with a local vehicle tracker config
- Stable-ID reassociation over short tracker ID switches
- Single-camera ground-plane distance estimate
- Per-track velocity vector estimate
- OpenCV visualization

## Install

```powershell
cd D:\mywork\code\embedded-contest-project\06_software\vision_obstacle_tracker
py -m pip install -r requirements.txt
```

The first run downloads the YOLO model weights if they are not already cached.

Optional packages:

```powershell
py -m pip install openvino  # CPU inference acceleration after --export-openvino
py -m pip install PyYAML    # richer YAML calibration-file parsing
```

The code has a simple YAML fallback for calibration files, so PyYAML is optional.

## Run USB Camera

```powershell
cd D:\mywork\code\embedded-contest-project\06_software\vision_obstacle_tracker
py vision_obstacle_tracker.py --source camera
```

The default live profile is `--runtime-profile balanced`, tuned to keep live FPS higher while preserving useful vehicle and bicycle recognition from a chest-mounted camera:

```text
Camera backend: FFmpeg MJPEG pipe
Camera: 1280x720 MJPEG @ 30fps requested
Tracker: vehicle_botsort.yaml
YOLO imgsz: 1024
YOLO confidence: 0.02
YOLO max detections: 50
Displayed classes: car,bicycle,motorcycle,bus,truck
ROI top crop: 0.0
Display every N frames: 1
Display scale: 1.0
Camera height: 1.2m
FOV: 120 degrees diagonal
Camera pitch: 5 degrees downward
Distance mode: fused ground projection + vehicle size
```

The display window now uses native scale by default. Changing `--display-scale` only changes the preview size; YOLO still receives the original captured frame.

The default keeps a sensitive realtime profile for moving vehicles. `vehicle_botsort.yaml` uses BoT-SORT, longer lost-track buffering, low-score association, and sparse optical-flow camera-motion compensation to reduce ID switches on a chest-mounted moving camera. A stable-ID layer also reconnects short tracker ID changes when class and ground position still match.

Live FFmpeg input is configured with low DirectShow buffering and a latest-frame reader. If YOLO is slower than the camera, older frames are dropped and the next inference uses the newest available frame instead of processing a backlog.

Runtime profiles:

```powershell
py vision_obstacle_tracker.py --source camera --runtime-profile realtime
py vision_obstacle_tracker.py --source camera --runtime-profile cpu_demo
py vision_obstacle_tracker.py --source camera --runtime-profile balanced
py vision_obstacle_tracker.py --source camera --runtime-profile quality
```

`realtime` requests `960x540`, `imgsz=512`, `conf=0.03`, and `max_det=50`; `cpu_demo` requests `960x540`, `imgsz=640`, `conf=0.05`, and `max_det=40`; `balanced` requests `1280x720`, `imgsz=1024`, `conf=0.02`, and `max_det=50`; `quality` requests `1920x1080`, `imgsz=1024`, `conf=0.02`, and `max_det=50`. Explicit `--width`, `--height`, `--imgsz`, `--conf`, and `--max-det` values override the selected profile.

PyTorch CPU with `imgsz=1024` is usually slow. For local demos, start with `--runtime-profile cpu_demo --roi-top-ratio 0.20`, then compare OpenVINO.

For better CPU inference speed on supported Intel/CPU systems, optionally install OpenVINO, export the YOLO model, and reload the exported model:

```powershell
py -m pip install openvino
py vision_obstacle_tracker.py --source camera --export-openvino
```

The first `--export-openvino` run creates an OpenVINO model folder beside the original YOLO weights. Later runs can use that exported folder directly with `--model`, or keep using the `.pt` path and ask the program to prefer the existing OpenVINO export:

```powershell
py vision_obstacle_tracker.py --source camera --model yolo11n.pt --prefer-openvino
```

`--prefer-openvino` does not export automatically. If `yolo11n_openvino_model` already exists beside `yolo11n.pt`, it loads that folder and prints `Loading OpenVINO model`; otherwise it falls back to the original model and prints a hint to run `--export-openvino` first. OpenVINO is optional and is not required by `requirements.txt`.

If you need to show every COCO class instead of only traffic-related targets:

```powershell
py vision_obstacle_tracker.py --source camera --target-classes all
```

`--target-classes` is now applied before Ultralytics YOLO tracking through the `classes=` argument when possible, and the existing post-processing filter is still kept as a safety check.

Manual high-quality requests are still available, but they are usually too slow for live tracking on this CPU-only path:

```powershell
py vision_obstacle_tracker.py --source camera --width 2560 --height 1440 --imgsz 960
```

If FFmpeg camera opening fails, try the OpenCV backend:

```powershell
py vision_obstacle_tracker.py --source camera --camera-backend opencv --camera-index 1 --width 1280 --height 720 --imgsz 416
```

Live FFmpeg camera input uses a low-latency latest-frame reader. If YOLO runs slower than the camera, older frames are dropped and the visualization processes the newest available frame instead of building delay.

If it opens the wrong camera, try:

```powershell
py vision_obstacle_tracker.py --source camera --camera-index 0
```

## Run A Recorded Video

```powershell
cd D:\mywork\code\embedded-contest-project\06_software\vision_obstacle_tracker
py vision_obstacle_tracker.py --source video --video D:\mywork\code\embedded-contest-project\08_media\camera_data\your_video.mp4
```

Recorded-video preview defaults to realtime mode. A background reader decodes the MP4 sequentially at the video's original FPS and keeps only the newest frame. If YOLO inference is slower than the video's original FPS, stale video frames are dropped without doing expensive H.264 random seeks.

Optional: save the overlay output:

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --save-output D:\path\overlay.mp4
```

For full offline export, process every frame without opening the preview window:

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --video-every-frame --no-display --save-output D:\path\overlay_full.mp4
```

Automated short test without a display window:

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --max-frames 30 --no-display --save-output D:\path\overlay.mp4
```

## Useful Settings

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --imgsz 960 --conf 0.10 --display-scale 1.0
```

## Recommended CPU Demo Commands

PyTorch CPU quick test:

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --profile
```

OpenVINO recommended path after one explicit `--export-openvino` run:

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --prefer-openvino --profile
```

Risk tuning with CSV diagnostics:

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --prefer-openvino --risk-log-csv D:\path\risk_log.csv --profile
```

Risk tuning with compact overlay plus full debug CSV:

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --self-mask-bottom-ratio 0.92 --prefer-openvino --overlay-verbosity debug --risk-log-csv D:\path\risk_log.csv --profile
```

Bottom foreground / self-object filter comparison:

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --self-mask-bottom-ratio 0.92 --overlay-verbosity debug --risk-log-csv D:\path\risk_log.csv --profile
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --disable-self-object-filter --overlay-verbosity debug --risk-log-csv D:\path\risk_log_no_self_filter.csv --profile
```

Performance profiling and CPU-load controls:

```powershell
py vision_obstacle_tracker.py --source camera --profile
py vision_obstacle_tracker.py --source camera --roi-top-ratio 0.20 --profile
py vision_obstacle_tracker.py --source camera --display-every-n 3 --profile
py vision_obstacle_tracker.py --source camera --prefer-openvino --profile
```

`--profile` prints a sliding average about once per second for `capture`, `roi/crop`, `enhance`, `ego-motion`, `infer+track`, `postprocess`, `risk`, `draw`, and `display/write`. Use it to see whether the current bottleneck is camera capture, optical-flow ego-motion estimation, YOLO inference/tracking, contrast enhancement, overlay drawing, display refresh, or video writing.

`--roi-top-ratio` crops the top part of the frame before YOLO inference. For example, `--roi-top-ratio 0.20` sends only the lower 80% of the image to YOLO, which can reduce time spent on sky, ceiling, building tops, and other upper-frame regions that are usually irrelevant for ground obstacles. The detection boxes are restored to full-frame coordinates before distance, speed, risk, overlay, and video writing. If the crop is too large, far targets that first appear near the horizon can be missed; start with `0.15` or `0.20` and compare profile output before going higher.

`--display-every-n` lowers OpenCV preview refresh cost. `--display-every-n 2` refreshes the window every second processed frame, while inference, tracking, risk calculation, and optional video writing still run for every processed frame. `--no-display` still disables the window completely. `--save-output` still writes every processed frame with overlay.

`--overlay-verbosity` controls how much text is drawn on each detection box. `minimal` shows class, distance, and risk level; `normal` shows ID, class, distance, speed, risk, CPA/TTC, and corridor zone; `debug` adds quality, velocity vector, trajectory, risk terms, and cap reason. The risk CSV remains detailed regardless of this display setting.

`--self-mask-bottom-ratio` controls the bottom foreground self-object filter. The default `0.92` only targets boxes very close to the lower image edge. It is meant to remove camera-wearer equipment such as handlebar, backpack edge, body edge, support bracket, or other fixed foreground parts when they are misdetected as `bicycle`, `motorcycle`, or `person`. It is not a general obstacle deletion tool. Use `--disable-self-object-filter` to turn it off for A/B comparison while keeping bbox diagnostics in the CSV.

Suggested comparison commands:

```powershell
py vision_obstacle_tracker.py --source camera --runtime-profile balanced --profile
py vision_obstacle_tracker.py --source camera --runtime-profile balanced --roi-top-ratio 0.20 --profile
py vision_obstacle_tracker.py --source camera --runtime-profile balanced --roi-top-ratio 0.20 --display-every-n 3 --profile
py vision_obstacle_tracker.py --source camera --runtime-profile balanced --prefer-openvino --roi-top-ratio 0.20 --profile
```

For recorded video, compare full offline processing without display overhead:

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --video-every-frame --no-display --profile --max-frames 300
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --video-every-frame --no-display --roi-top-ratio 0.20 --prefer-openvino --profile --max-frames 300
```

For faster CPU processing:

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --imgsz 416
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --imgsz 320
```

Calibration settings:

```powershell
--camera-height 1.2 --camera-pitch 5 --fov 120 --fov-type diagonal
```

### Camera Calibration

For better distance accuracy, pass a real calibration file:

```powershell
py vision_obstacle_tracker.py --source camera --calibration-file D:\path\camera_calibration.json
```

Supported JSON/YAML fields:

```json
{
  "image_width": 1280,
  "image_height": 720,
  "camera_matrix": [[920.0, 0.0, 640.0], [0.0, 918.0, 360.0], [0.0, 0.0, 1.0]],
  "dist_coeffs": [-0.12, 0.04, 0.0, 0.0, 0.0],
  "camera_height_m": 1.2,
  "camera_pitch_deg": 5.0,
  "distance_scale": 1.0
}
```

When `camera_matrix` is present, the tracker uses independent `fx/fy/cx/cy` values and undistorts detection foot-points with OpenCV before ground projection. If no calibration file is given, it keeps the old FOV-based fallback using `--camera-height`, `--camera-pitch`, `--fov`, and `--fov-type`.

If the calibration file was created at a different image size, intrinsics are scaled to the runtime frame size. This is useful when a camera was calibrated at 1920x1080 but the live profile runs at 1280x720.

Runtime pitch adjustment is available only when the display window is open:

```text
[: decrease pitch by --pitch-adjust-step degrees
]: increase pitch by --pitch-adjust-step degrees
```

Use `--pitch-adjust-step 0.25` and optional `--pitch-smoothing 0.5` for slower visual tuning. In `--no-display` mode there are no hotkeys, so set pitch from the command line or calibration file.

Distance and speed tuning:

```powershell
py vision_obstacle_tracker.py --source camera --distance-mode fused
py vision_obstacle_tracker.py --source camera --distance-scale 1.25 --speed-scale 1.25
py vision_obstacle_tracker.py --source camera --camera-pitch 3
```

If measured distance is consistently too small, first lower `--camera-pitch` or raise `--distance-scale`. If distance jitters, lower `--distance-smoothing` toward `0.25`; if speed reacts too slowly, raise it toward `0.6`. `--distance-mode size` uses vehicle/bicycle typical dimensions only, while `--distance-mode ground` uses only the ground-plane projection. In fused mode, ground/size weighting is adaptive; `--size-weight` is now only a fallback/debug value used when confidence data is unavailable.

### Adaptive Distance Fusion

`--distance-mode fused` adapts its ground-vs-size weighting using detection quality. It lowers ground confidence for boxes near the image edge, truncated boxes, boxes whose bottom point is too high in the frame, and very small far boxes. It also rejects unreliable ground projection near the horizon using `min_ground_angle_deg`, `max_reliable_ground_distance_m`, and `max_reliable_distance_m` from calibration settings. Quality flags such as `near_horizon`, `ground_too_far`, and `distance_clamped` are written to the CSV log.

Overlay labels show the selected distance source and distance quality:

```text
d=8.3m(fused,q=0.72)
```

`q` here is distance confidence. It is also written to the optional CSV risk log as `distance_confidence`, with `ground_confidence`, `size_confidence`, and `quality_flags`.

### Ego Motion Quality

The tracker can estimate lightweight global image motion with OpenCV optical flow. Strong camera shake or coherent body motion does not stop detection, but it lowers `velocity_confidence` moderately. Risk scoring keeps a confidence floor so a real CUTIN/CLOSING target is not multiplied down to SAFE only because camera motion was noisy.

Overlay labels include velocity quality:

```text
qV=0.62
```

Use profile output to see ego-motion cost:

```powershell
py vision_obstacle_tracker.py --source camera --ego-motion-mode light --ego-motion-every-n 5 --profile
py vision_obstacle_tracker.py --source camera --ego-motion-mode off --profile
```

`--ego-motion-mode light` runs optical flow on a downscaled frame. `--ego-motion-every-n 5` runs it every fifth processed frame and uses neutral motion quality on skipped frames. `--ego-motion-mode off` disables this extra optical-flow pass; BoT-SORT may still use its own tracker-side GMC from `vehicle_botsort.yaml`.

Optional low-light enhancement:

```powershell
py vision_obstacle_tracker.py --source camera --enhance auto
py vision_obstacle_tracker.py --source camera --enhance clahe
py vision_obstacle_tracker.py --source camera --enhance off
```

## Risk Warning Overlay

Each tracked target displays distance, speed, warning level, CPA/TTC, and corridor zone in the default box label. Use `--overlay-verbosity debug` to also show distance quality, velocity quality, velocity vector, `RiskScore`, motion pattern, trajectory distance (`TRAJ`), risk terms, severity class, action reason, and cap reason. Box colors are:

```text
SAFE: green
ATTENTION: yellow
CAUTION: orange-yellow
DANGER: orange-red
EMERGENCY: red
```

The output has two layers. `raw_risk_level` is the candidate level computed from CPA, corridor zone, target class, speed, distance, and motion quality. `display_risk_level` is the actual box color and the level intended for the later vibration module. Display risk is stabilized across frames so a single bad monocular distance or velocity spike does not immediately become a strong warning.

The CSV also exposes `visual_risk_level` and `haptic_risk_level`. `visual_risk_level` follows the stabilized box warning. `haptic_risk_level` is stricter and is intended for the future vibration output. Remote traffic can remain visually interesting as ATTENTION for debugging while still producing `haptic_risk_level=SAFE` when there is no future path conflict.

Default confirmation behavior:

```text
ATTENTION: can display quickly, usually first frame.
CAUTION: requires 2 confirmed frames by default.
DANGER: requires 3 confirmed frames by default.
EMERGENCY: requires confirmed frames, except clear fast path cases such as current distance <= 0.8m or high-quality extremely short TTC/CPA.
Downgrade: held briefly and drops step by step to avoid flicker.
```

Low observation quality, short track age, low velocity confidence, high position jitter, speed spikes, and velocity reversals add conservatism. They usually cap displayed warning to ATTENTION unless the target is already extremely close or the dangerous condition is stable for multiple frames.

### Self Object / Bottom Foreground Filter

For a wearable camera, the lower image area can include the user's own handlebar, backpack edge, clothing, hand, support bracket, or other fixed equipment. YOLO can misclassify these as `bicycle`, `motorcycle`, or `person`. These are not external obstacles, so they should not trigger haptic warnings.

The `SelfObjectFilter` runs after tracking and before risk assessment. It checks:

```text
bbox bottom ratio near the lower image edge
whether the bbox is truncated by the bottom frame boundary
large bottom foreground area for bicycle/motorcycle/person
track staying fixed at the bottom across recent frames
```

Filtered targets are kept in `risk_log.csv` for debugging but forced to SAFE with:

```text
ignored_reason=self_object_bottom_foreground
self_object_score
bbox_bottom_ratio
bbox_truncated_edges
```

Default tuning:

```powershell
--self-mask-bottom-ratio 0.92
```

If a real obstacle near the lower edge is being filtered incorrectly, reduce the bottom foreground score by raising the ratio slightly, or disable the filter temporarily:

```powershell
--disable-self-object-filter
```

This filter should only affect bottom-truncated, self-like foreground boxes. Normal bicycles, e-bikes, motorcycles, cars, or pedestrians in the forward road/path remain in the detection and risk pipeline.

### Visual Risk vs Haptic Warning / 视觉风险与震动风险

The warning outputs are intentionally split:

```text
raw_risk_level: single-frame candidate from CPA, TTC, corridor, class, speed, and quality.
visual_risk_level: stabilized visual box color for on-screen debugging.
haptic_risk_level: stricter output for the future vibration module.
```

Rules of thumb:

```text
REMOTE_TRAFFIC without path_conflict: visual can be ATTENTION, haptic stays SAFE.
Moving away without future conflict: visual and haptic stay SAFE.
Bottom self object: ignored_reason is set, visual and haptic stay SAFE.
Edge-truncated low-quality box: capped by edge_truncated_cap; no DANGER/EMERGENCY haptic from a single frame.
Real stable path conflict: visual upgrades after confirmation; haptic can upgrade once the conflict is path-related and stable.
```

Future vibration control should use `haptic_risk_level` and `warning_action`, not raw single-frame risk.

### Warning Level Semantics / 预警等级语义

This project uses warning levels as vibration-prewarning semantics, not just score buckets:

```text
SAFE:
  安全，不提醒，不震动。

ATTENTION:
  需要注意，轻微提醒。适合远处可能接近的大车、近侧目标、或需要用户抬头确认的情况。

CAUTION:
  有被碰到的可能，需要注意观察。适合数秒内可能进入前方走廊或个人空间的目标。

DANGER:
  有可能发生较严重交通事故，需要拉开距离或主动躲避。适合大车或高速摩托/电动车在较短时间内进入个人空间或正前方路径。

EMERGENCY:
  高概率发生严重交通事故，一定要立刻躲避。适合当前已经进入个人安全半径、极短 TTC、极短 CPA 且观测质量明确的情况。
```

The model is not “warn whenever a car is visible”. It combines:

```text
CPA time / cpa_time_s
CPA distance / cpa_distance_m
corridor zone / PATH, SIDE, REMOTE, SIDE_STATIC, UNK
target severity class / large_vehicle, small_rider, unknown_or_other
current distance and radial closing speed
target speed segment / low speed, normal, high speed
track age, velocity confidence, position jitter, observation quality
```

### Severity Profiles / 类别提前量

Targets are grouped by accident severity and avoidability:

```text
large_vehicle: car, truck, bus
  Higher mass and higher accident severity. Candidate warnings start earlier.
  ATTENTION horizon: about 6.0s
  CAUTION horizon: about 4.8s
  DANGER horizon: about 3.0s
  EMERGENCY horizon: about 1.3s
  warning radius: about 2.4m
  personal space radius: about 0.9m

small_rider: bicycle, motorcycle
  More avoidable at low speed, so low-speed side motion is more conservative.
  ATTENTION horizon: about 4.0s
  CAUTION horizon: about 3.0s
  DANGER horizon: about 2.0s
  EMERGENCY horizon: about 1.0s
  warning radius: about 1.5m
  personal space radius: about 0.75m

unknown_or_other:
  Middle profile for classes outside the traffic-focused set.
```

Large vehicles can become candidate ATTENTION/CAUTION earlier when CPA shows they will enter the walking corridor or personal space. This does not mean they immediately trigger strong vibration: the displayed warning still passes multi-frame confirmation and quality checks. Low-speed bicycles or motorcycles that stay outside PATH are capped to ATTENTION or SAFE; high-speed motorcycles entering personal space can still become DANGER.

### Vibration Mapping / 震动提醒映射

The current code writes `warning_action` for each risk level so the later vibration module can map it directly:

```text
SAFE:      none                         不震动
ATTENTION: short_weak_pulse             短弱震一次
CAUTION:   medium_interval_pulse        间歇中等震动
DANGER:    strong_fast_pulse            连续强震或快速脉冲
EMERGENCY: continuous_high_frequency    高频连续强震
```

### CPA, Corridor, And Caps / CPA、走廊和上限

### Future Conflict Gate / 未来冲突闸门

Before any CAUTION/DANGER/EMERGENCY candidate is allowed, the model checks whether the target will actually enter the wearer's personal safety circle or the finite forward walking corridor. The gate is logged through `path_conflict` and `conflict_reason`.

```text
path_conflict: true only for personal-space entry or finite corridor entry
moving_away: dot(p, v) >= 0 or recent distance trend is receding, with no future conflict
will_enter_personal_space: future motion enters the class-specific personal radius
will_enter_warning_corridor: future motion enters |x| <= corridor_half_width and 0 <= z <= corridor_depth
personal_entry_time_s: first time entering the safety circle
corridor_entry_time_s: first time entering the finite walking corridor
min_future_distance_m: nearest finite-horizon distance used by the risk terms
```

If `moving_away=True` and `path_conflict=False`, the candidate risk is forced to SAFE unless the target is already inside personal space. If `path_conflict=False`, TTC/DRAC/closing speed can only support ATTENTION-level candidates; they cannot push the target to CAUTION or above. Remote lateral traffic and side passing therefore stay SAFE/ATTENTION unless the finite future path really enters the wearer's corridor or personal radius.

The warning model is a calibrated rule model, not a trained crash-probability model. It prioritizes whether a target enters the camera-wearer's finite forward corridor within the configured time horizon, rather than treating every infinite straight-line trajectory as dangerous.

```text
CPA: closest point of approach within the current constant-velocity estimate
CPA time: seconds until that closest approach
CPA distance: distance from the wearer origin at closest approach
corridor zone: PATH, SIDE, REMOTE, SIDE_STATIC, or UNK
TRAJ: diagnostic distance from the origin to the infinite motion line
TTC: time to collision along the radial closing line
DRAC: deceleration required to avoid collision
radial closing speed: speed along the target-to-camera line
```

Remote traffic remains conservative. `remote_traffic_no_path_conflict` caps far lateral traffic to SAFE or ATTENTION when the finite future path does not enter personal space or the walking corridor. `moving_away_no_future_conflict` forces clearly receding targets to SAFE. `no_corridor_entry` records objects whose CPA/TTC terms are not allowed to escalate because the finite path never enters the safety regions. A large vehicle in REMOTE can escape that cap only when the finite future path shows a real conflict, recorded as `remote_large_vehicle_path_conflict`. Roadside stopped motorcycles/e-bikes are capped by `side_static`; low-speed non-path riders are capped by `low_speed_non_path`; side-edge truncated boxes with weak distance/velocity confidence are capped by `edge_truncated_cap`; short or unstable single-frame CPA spikes are capped by `unstable_single_frame_cpa` or `unstable_track` unless they are already extremely close.

Risk score is still computed and logged for sorting and debugging. It combines CPA-distance risk, TTC risk, DRAC risk, radial closing risk, optional near-static risk, and the existing vehicle multipliers. Final candidate level is then adjusted by explicit action rules and contextual caps. This is why `risk_action_reason` and `risk_cap_reason` are both important when tuning.

### Risk Logging

For debugging risk decisions frame by frame:

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --no-display --risk-log-csv D:\path\risk_log.csv --max-frames 300
```

The CSV includes frame index, track ID, class, detection confidence, observation quality, distance components, distance/velocity confidence, velocity stability, position jitter, distance trend, approach consistency, path-conflict consistency, quality flags, self-object diagnostics (`ignored_reason`, `self_object_score`, `bbox_bottom_ratio`, `bbox_truncated_edges`), ground position, velocity, ego-motion magnitude, radial closing speed, trajectory distance, CPA time, CPA distance, CPA validity, future-conflict fields (`moving_away`, `approaching`, `path_conflict`, `will_enter_personal_space`, `will_enter_warning_corridor`, `personal_entry_time_s`, `corridor_entry_time_s`, `min_future_distance_m`, `conflict_reason`), TTC, DRAC, motion pattern, corridor zone, risk cap reason, severity class, warning action, warning time horizon, warning radius, risk action reason, raw risk score/level, displayed risk score/level, `visual_risk_level`, `haptic_risk_level`, risk term breakdown (`trajectory_risk`, `ttc_risk`, `drac_risk`, `closing_risk`, `static_obstacle_risk`), and stabilizer diagnostics (`stabilizer_pending_level`, `stabilizer_pending_count`, `stabilizer_required_frames`, `stabilizer_reason`).

### Risk Model Tuning

Start with calibration before changing risk thresholds. If distances are biased, fix `camera_matrix`, `camera_height_m`, `camera_pitch_deg`, or `distance_scale` first. If velocity is noisy, check `qV`, `velocity_stability`, `position_jitter_m`, `distance_trend_mps`, `approach_consistency`, `path_conflict_consistency`, ego-motion flags, lighting, `--ego-motion-mode`, `--ego-motion-every-n`, and `--distance-smoothing`. Use `--risk-log-csv` to compare raw risk against displayed and haptic risk; if raw risk is correct but colors lag, inspect `stabilizer_reason`, `stabilizer_required_frames`, and whether low `path_conflict_consistency` added confirmation frames. If visual risk is ATTENTION but haptic stays SAFE, check whether `path_conflict=False`, `corridor_zone=REMOTE`, `moving_away=True`, `ignored_reason` is set, or `risk_cap_reason` includes `edge_truncated_cap`. If raw risk itself is wrong, inspect `path_conflict`, `moving_away`, `will_enter_personal_space`, `will_enter_warning_corridor`, `personal_entry_time_s`, `corridor_entry_time_s`, `conflict_reason`, `cpa_time_s`, `cpa_distance_m`, `corridor_zone`, `risk_cap_reason`, `bbox_truncated_edges`, `TRAJ`, `TTC`, `motion_pattern`, `distance_confidence`, `velocity_confidence`, and the risk term breakdown.

To judge whether the false-positive fix is working:

```text
Roadside static motorcycle/e-bike: should not become CAUTION.
Bottom handlebar/backpack/body-edge false bicycle: should show ignored_reason=self_object_bottom_foreground and stay SAFE.
Remote lateral traffic: should not become DANGER, and haptic_risk_level should usually stay SAFE when path_conflict is false.
Right/left edge-truncated vehicle with a single CPA spike: should show edge_truncated_cap and should not become DANGER/EMERGENCY.
Bicycle/e-bike actually entering the front path: should become ATTENTION/CAUTION.
Large vehicle actually entering the walking corridor: should still become early ATTENTION/CAUTION and then DANGER after stable confirmation if it enters personal space soon.
risk_log.csv should contain ignored_reason, self_object_score, bbox_bottom_ratio, bbox_truncated_edges, visual_risk_level, haptic_risk_level, cpa_time_s, cpa_distance_m, cpa_valid, moving_away, path_conflict, will_enter_personal_space, will_enter_warning_corridor, personal_entry_time_s, corridor_entry_time_s, min_future_distance_m, conflict_reason, distance_trend_mps, approach_consistency, path_conflict_consistency, corridor_zone, severity_class, warning_action, risk_action_reason, risk_cap_reason, and stabilizer_required_frames.
```

If live FPS stays low at every requested resolution, the camera delivery path is the limit rather than YOLO. In that case, check lighting, exposure, and the camera driver settings; reducing resolution will not help until the camera actually supplies frames faster. A common cause is auto exposure in a dim scene lowering the camera to about 5-6 FPS.

## Display Controls

- `q` or `Esc`: exit
- `Space`: pause/resume
- `[`: decrease runtime camera pitch by `--pitch-adjust-step`
- `]`: increase runtime camera pitch by `--pitch-adjust-step`

## Distance And Speed Limits

This first version uses a single-camera ground-plane approximation:

- The bottom center of each detection box is projected onto a flat ground plane.
- Distance depends on camera height, pitch, field of view, and detection box quality.
- Velocity is estimated from recent smoothed ground points using robust short-history motion, with position jitter and direction reversal lowering velocity confidence.

The numbers are useful for early algorithm testing, but they are not final safety-grade measurements. Accurate distance/speed needs careful camera calibration and, in a later system stage, validation against additional sensors or measured ground truth.

## Tests

```powershell
cd D:\mywork\code\embedded-contest-project\06_software\vision_obstacle_tracker
py -m unittest discover -s tests -v
```

## SS928 板端事件输出（旧单摄兼容示例）

`board_cpu` 是 CPU 协议联调基线，不表示已经使用 SS928 NPU。下面的 `side auto` 只用于旧单摄兼容测试，不是正式 systemd 默认：

```sh
python3 vision_obstacle_tracker.py \
  --source camera --camera-device /dev/video0 \
  --runtime-profile board_cpu --model /root/smartbag/models/yolo11n.pt \
  --no-display --side auto --center-side both \
  --emit-alert-jsonl --alert-min-level 1 --alert-rate-limit 0.5
```

stdout 只输出 compact `vision_alert` JSONL，模型加载、profile 和普通日志写 stderr。事件等级来自多帧稳定后的 `haptic_level`；风险消失会立即发 level 0。同侧同等级受 rate limit 限制。`--side left|right` 用于双摄固定方向；单摄 `auto` 根据 `x_m` 和 `--side-dead-zone` 路由。

`--detector-backend ultralytics` 是当前完整实现。`--detector-backend ss928_om` 只保留明确接口和未实现错误；OpenVINO 不等于 SS928 NPU，不能用它冒充 `.om` 后端。

## SS928 双 USB 摄像头运行

正式板端每个进程固定占有一个物理相机，不使用 `--side auto`：

```sh
python3 vision_obstacle_tracker.py --source camera \
  --camera-device /dev/v4l/by-id/LEFT-video-index0 \
  --runtime-profile board_dual_balanced --side left \
  --calibration-file /etc/smartbag/calibration-left.json \
  --model /root/smartbag/models/yolo11n.pt --no-display \
  --emit-alert-jsonl --profile --stream-bind 127.0.0.1 --stream-port 18081
```

右侧使用另一设备、`--side right`、`calibration-right.json` 和端口 18082。`board_dual_balanced` 默认请求已在当前 UVC 描述符中确认的 640x480@30、YOLO `imgsz=512`、推理上限 8 FPS；描述符 30 FPS 不代表实测能持续达到。直接命令行的预览默认 640x360，部署配置使用保持 4:3 的 480x360、JPEG quality 70、8 FPS。板上不足时改 `board_cpu`，不要先牺牲风险稳定器或让 raw risk 直接驱动震动。

新增参数：

```text
--camera-fps/--fps              相机请求帧率
--inference-fps-limit           live detector 循环上限，0 表示不限
--process-every-n               每 N 个采集帧交付一个；capture 仍持续排空
--camera-reconnect-attempts     断流后的有限重连次数
--camera-reconnect-backoff      重连初始退避秒数
--stream-bind/--stream-port     detector 本地 HTTP 服务；port=0 关闭
--jpeg-stream-width/height      手机 JPEG 尺寸，不改变 YOLO 输入
--jpeg-quality                  20..95
--stream-fps-limit              每个 MJPEG 客户端上限
--stream-access-token           可选 detector 本地 token
```

相机采集使用容量 1 的 latest-frame buffer，旧帧被覆盖而不是排队。HTTP 只读取本进程已有 raw/overlay 帧，不二次打开相机；手机慢或断开不会阻塞检测。没有视频客户端时不会主动执行 JPEG 编码。profile 保留 `capture`、`infer+track`、postprocess、risk、draw、display/write、total，并额外报告 JPEG、客户端数、stream FPS 和 dropped frames；当前 Ultralytics `model.track()` 无法可靠拆分 inference 与 tracker，因此不伪造两项独立耗时。

detector HTTP 提供 `/api/v1/camera/<side>/status`、`snapshot.jpg` 和 `mjpeg`。外部双路聚合 API 和浏览器页由 `dual_camera_gateway.py` 提供，部署方法见 `09_deliverables/board_deploy/README.md`。

## SS928 实验性交替双摄（单模型）

`alternating_dual_camera_tracker.py` 是默认关闭的时间复用入口。它保持两个 UVC fd/mmap 缓冲，但严格按“左 STREAMON -> 预热/取帧 -> STREAMOFF -> 推理 -> 右 STREAMON”循环；任何时刻最多一路 streaming。它不是同步双摄，未激活侧没有新观测，也不会被当成 SAFE。

检测只加载一个 Ultralytics 模型并调用 `model.predict()`；左右各自持有独立 BoT-SORT、`StableTrackIdManager`、`TrackState`、`RiskModel`、`RiskWarningStabilizer`、`SelfObjectFilter`、标定和 risk CSV。禁止使用一个 `model.track(..., persist=True)` 交替喂左右画面。输出震动等级仍来自跨时间片稳定后的 `haptic_level`，raw/visual risk 不直接控制 PWM。

### 调度、盲区和跟踪时间尺度

- `--inference-frames-per-slice` 默认 `1`：每片仍采集全部有效帧做采集统计，但只推理最后一张最新帧；旧帧立即跳过，没有无界队列。该值不得超过 `--frames-per-slice`。
- `capture_switch_blind_interval_ms` 只描述 STREAMOFF -> 下一侧 STREAMON -> 第一帧；`end_to_end_observation_gap_ms` 按同一侧两张真正进入视觉算法的帧时间计算，包含另一侧采集、解码、推理、跟踪、风险、overlay、JPEG 和调度。验收使用后者。
- `performance.csv` 和 `camera-events.csv` 记录各阶段 monotonic 时间、左右 E2E p50/p95/p99/max、跨侧 p95、已选/跳过帧、队列深度和最旧待处理帧龄。正常队列深度是 `0`，处理中的最新帧最多 `1`。
- 内存中的 switch/E2E/性能历史使用有界 deque；CSV 仍逐条落盘，切换总数、错误数、最大盲区和性能均值/峰值使用独立累计量，不受窗口淘汰影响。
- `--tracker-effective-fps-mode effective_side` 用每侧真实观测频率调整 tracker 的时间缓冲；距离速度、CPA 和 Future Conflict Gate 仍只使用真实 monotonic 时间。
- CAUTION/DANGER/EMERGENCY 默认至少跨不同 `slice_id` 确认。同一 burst 内多张帧不能普通路径直接满足 DANGER；紧急单 slice fast path 只允许极近、高质量冲突，并写入 `fast_path_reason`。

先运行无模型 A/B 测试：

```sh
python3 alternating_camera_test.py \
  --left-device /dev/v4l/by-path/LEFT-video-index0 \
  --right-device /dev/v4l/by-path/RIGHT-video-index0 \
  --width 640 --height 480 --fps 30 \
  --slice-ms 500 --warmup-frames 2 --frames-per-slice 4 \
  --duration-s 120 --backend v4l2_stream_toggle \
  --output-dir /var/log/smartbag/alternating-camera-runs

python3 alternating_camera_test.py \
  --left-device /dev/v4l/by-path/LEFT-video-index0 \
  --right-device /dev/v4l/by-path/RIGHT-video-index0 \
  --width 640 --height 480 --fps 30 --slice-ms 500 \
  --warmup-frames 2 --frames-per-slice 4 --duration-s 120 \
  --runtime-mode stream_only --serve-bind 0.0.0.0 --serve-port 8081 \
  --output-dir /var/log/smartbag/alternating-camera-runs
```

B 阶段页面为 `http://<板端地址>:8081/`。状态会标明当前 active side、另一侧缓存帧年龄和离线状态；gateway 只读缓存，不重新打开摄像头。A/B 没有 YOLO，也不生成 overlay，页面会自动选择 raw，按钮文字应为“切换为检测画面”；不能用 B 阶段证明 C 阶段检测 overlay 已通过。

若状态显示两侧 online 但页面黑屏，依次检查 `api/v1/status`、`snapshot.jpg?view=raw` 和 `mjpeg?view=raw`。单帧正常但连续流不刷新时，需确认网关没有只按 V4L2 sequence 去重，因为每次 STREAMOFF/STREAMON 后该序号可能重复；当前实现还比较采集时间和发布时间。

依赖齐全后才运行 C：

```sh
python3 alternating_dual_camera_tracker.py \
  --left-device /dev/v4l/by-path/LEFT-video-index0 \
  --right-device /dev/v4l/by-path/RIGHT-video-index0 \
  --left-calibration-file /etc/smartbag/calibration-left.json \
  --right-calibration-file /etc/smartbag/calibration-right.json \
  --model /root/smartbag/models/yolo11n.pt --tracker vehicle_botsort.yaml \
  --width 640 --height 480 --fps 30 --normal-slice-ms 500 \
  --warmup-frames 2 --frames-per-slice 4 --inference-frames-per-slice 1 \
  --tracker-effective-fps-mode effective_side --imgsz 416 --conf 0.08 \
  --min-confirm-slices-caution 2 --min-confirm-slices-danger 2 \
  --min-confirm-slices-emergency 2 --minimum-confirmation-interval-s 0.2 \
  --serve-bind 0.0.0.0 --serve-port 8080 --jpeg-quality 80 \
  --duration-s 60 --output-dir /var/log/smartbag/alternating-camera-runs \
  --risk-log-dir /var/log/smartbag
```

stdout 只用于 compact `vision_alert` JSONL；模型和普通日志写 stderr。状态变化使用 `event_kind=state_change`，有效风险的维持包使用 `heartbeat`；heartbeat 只刷新 PWM timeout，不进入 BLE/手机报警历史。切换到另一侧不会清除上一侧，超过 `--stale-observation-timeout-ms` 才安全清振。时间维度确认参数为 `--caution-confirm-duration-s`、`--danger-confirm-duration-s`、`--emergency-confirm-duration-s` 和 `--low-quality-extra-duration-s`，它们与原有确认帧数同时生效。

### 浏览器 raw/overlay

交替 detector 内部直接启动 gateway，不创建第二个摄像头进程。每侧缓存原始 MJPEG 和绘制后的 JPEG；raw 直接复用摄像头数据，overlay 才做绘制和编码。默认关闭 HTTP access log。接口：

```text
GET /
GET /api/v1/status
GET /api/v1/cameras
GET /api/v1/alternating/snapshot.jpg?view={raw|overlay}
GET /api/v1/alternating/mjpeg?view={raw|overlay}
GET /api/v1/camera/{left|right}/status
GET /api/v1/camera/{left|right}/snapshot.jpg?view={raw|overlay}
GET /api/v1/camera/{left|right}/mjpeg?view={raw|overlay}
```

访问 `http://<BOARD_IP>:8080/` 可查看低延迟交替画面和左右缓存对照，切换 raw/overlay，并查看 active/cached/offline、帧龄、风险、推理 FPS、E2E 间隔、模型、后端、CPU、RSS 和温度。`alternating/mjpeg` 始终转发左右两侧中最新的一帧，不排队回放旧帧；因此它比任一单侧流连贯，但并不代表两台摄像头同时 STREAMON。左右独立窗口中的未激活侧仍显示最近缓存帧。`--disable-video-gateway` 完全关闭它；`--access-token` 只适合可信局域网基线，公网仍需反向代理、HTTPS、认证和防火墙。视频不走 BLE。

### 安装外参与断线恢复

左右标定 JSON 都必须包含 `camera_matrix`、`dist_coeffs`、图像尺寸、相机高度/pitch、`mount_yaw_deg`、`mount_roll_deg`、`mount_x_m`、`mount_z_m`、`distance_scale`、`calibrated` 和 `calibration_version`。背包坐标定义为 x 向佩戴者右侧为正、z 向背包正后方为正；左相机 `mount_x_m < 0`，右相机 `mount_x_m > 0`，正 yaw 朝 x 正方向。像素地面点先转入背包坐标，再进入 TrackState/CPA/corridor。`--calibration-mode production` 拒绝 `calibrated=false`，diagnostic 仅警告。

运行时一侧 STREAMON/DQBUF/首帧失败会进入 `READ_FAILURE -> REOPEN_WAIT -> REOPENING -> RECOVERED/ONLINE`，关闭该侧 fd 和 mmap，另一侧继续。有限指数退避由 `--camera-reconnect-*` 控制；断开超过 `--tracker-reset-after-disconnect-s` 时只重置对应侧 tracker/TrackState/stabilizer。switch CSV 记录断开、重开、恢复、恢复帧和 tracker reset；软件无法知道物理拔线的精确瞬间时，`offline_detect_latency_ms` 保持空值。

### 板端依赖和当前边界

```sh
sudo sh /root/smartbag/board-deploy/install-board-cpu-deps.sh
sh /root/smartbag/board-deploy/check-runtime-deps.sh
# 仅在已有经 SHA256/ABI 核对的 cp310 linux_aarch64 wheelhouse 时：
sudo sh /root/smartbag/board-deploy/install-board-deps-offline.sh /path/to/wheelhouse
```

不要直接在资源受限板上盲装最新版 Ultralytics。系统 APT 可提供 OpenCV/NumPy；torch、torchvision、Ultralytics 和 lap 必须以匹配 Python 3.10/aarch64 的离线 wheel 验证。`Ss928OmBackend` 仍因通用内存帧 ACL API、配套头文件和已核对的预处理/输出定义不足而 BLOCKED；OpenVINO 不是 SS928 NPU。

### 微信小程序和 session

小程序双摄页从本地 storage 读取板端地址，不写死 IP。每侧最多一个 snapshot 请求，图片完成后再调度下一次；暂停或页面隐藏时停止请求，恢复后重连，失败时指数退避。可切换 raw/overlay 和单侧实时查看；聚焦一侧时另一侧降低刷新。`wx.previewImage` 不作为实时视频实现。微信真机、AppID、HTTPS 和合法域名必须另做真机验证。

原始 session 在 `08_media/alternating_camera_runs/`（PC）或 `/var/log/smartbag/alternating-camera-runs/`（板端），包括 `session.json`、四份 CSV、错误日志和 summary。逐帧 risk CSV 正式默认关闭；定时清理只删除非活动旧 session。大型原始数据不提交 Git；可提交的匿名摘要在 `07_tests/results/alternating_camera/latest-summary.md`。2026-07-19 的 30 分钟纯采集已通过，但完整 E2E、板端模型、带框 overlay、PWM/BLE 和修复后长测仍未通过；正式默认保持 `fixed_dual_process` 且 `alternating_camera.enabled=false`。
