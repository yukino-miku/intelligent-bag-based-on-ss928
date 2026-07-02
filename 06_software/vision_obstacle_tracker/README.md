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

Each tracked target displays distance, speed, distance quality, velocity quality, `RiskScore`, warning level, motion pattern, TTC, and trajectory distance (`TRAJ`) in the box label. Box colors are:

```text
SAFE: green
ATTENTION: yellow
CAUTION: orange-yellow
DANGER: orange-red
EMERGENCY: red
```

To suppress one-frame warning flashes from bad distance or velocity estimates, box color uses a display-level stabilizer. ATTENTION can display on the first frame. High-quality CAUTION, especially CUTIN/CLOSING with short TTC or very small trajectory clearance, can also display immediately. DANGER/EMERGENCY still require confirmation by default, and low observation quality adds one extra confirmation frame. A very short emergency path can still display immediately when the raw assessment is EMERGENCY and `TTC <= 0.8s` or current distance is `<= 0.8m`. Downgrades are held briefly for 2 frames so colors do not flicker when scores sit near a threshold.

The warning model is a calibrated rule model, not a trained crash-probability model. It prioritizes the predicted straight-line trajectory clearance over raw distance. The main indicators are:

```text
TRAJ: distance from the camera-wearer origin to the target's current constant-velocity trajectory line
TTC: time to collision along the radial closing line
DRAC: deceleration required to avoid collision
radial closing speed: speed along the target-to-camera line
```

Risk score weights:

```text
trajectory distance: 4.00
TTC: 2.00
DRAC: 1.50
radial closing speed: 1.50
near static obstacle: 1.40
```

Vehicle risk multipliers are applied after the weighted average and before the final clamp:

```text
bicycle: 0.92
motorcycle: 0.96
car: 1.00
truck: 1.10
bus: 1.10
other: 1.00
```

Risk levels:

```text
SAFE: RiskScore < 0.40
ATTENTION: 0.40-0.60
CAUTION: 0.60-0.70
DANGER: 0.70-0.80
EMERGENCY: >= 0.80
```

Closing speed is radial closing speed, computed along the actual line from the camera wearer to the target. A target moving sideways with only a small negative `vz` is no longer treated as strongly closing unless its full motion vector points toward the wearer.

Detection confidence is used only by YOLO/tracking. It is not multiplied into the warning score, because a weak detection can still describe a real obstacle and should not create or suppress risk by itself.

`vz >= 0` is no longer a hard SAFE rule. The model uses radial closing speed, trajectory clearance, TTC/DRAC, and near-static distance. This prevents lateral cut-in targets and close static obstacles from being discarded just because the forward-axis velocity is non-negative.

Trajectory distance is computed from the target's current ground position and velocity as the distance from the origin to that motion line: `abs(x * vz - z * vx) / sqrt(vx^2 + vz^2)`. If speed is too close to zero, the current ground distance is used instead.

Hard safety thresholds are applied before scoring where appropriate: targets are SAFE when `TTC > 5.0s`; bicycles are SAFE when `TRAJ > 1.5m`; motor vehicles (`car`, `motorcycle`, `truck`, `bus`) are SAFE when `TRAJ > 3.0m`, unless the target is already a near static obstacle. Targets classified as moving away are SAFE unless near-static distance risk is active.

If the target remains inside those safety thresholds, the score is a weighted average of trajectory-distance risk, TTC risk, DRAC risk, radial-closing-speed risk, and optional near-static-obstacle risk, then multiplied by the vehicle risk multiplier. Trajectory-distance risk uses a saturating power curve, `1 - (TRAJ / safe_distance)^2`. TTC risk also uses a saturating power curve: `1 - ((TTC - 1.5) / (5.0 - 1.5))^2` for `1.5s < TTC < 5.0s`, with `TTC <= 1.5s` saturated at `1.0` and `TTC >= 5.0s` contributing `0.0`. Velocity confidence no longer directly multiplies these risk terms to near zero; TTC/DRAC/closing use a floor, and trajectory risk is kept independent because it is the key CUTIN signal.

Motion pattern labels in the overlay and risk log are:

```text
STATIC: static or uncertain motion
AWAY: moving away
CUTIN: lateral cut-in toward the camera wearer
CLOSING: head-on or radial closing
NEAR: near static obstacle
```

CUTIN and NEAR patterns have explicit score floors. A CUTIN target with very small `TRAJ` reaches at least ATTENTION, and short TTC or very small trajectory clearance reaches at least CAUTION. A near static obstacle under 1.5m reaches at least ATTENTION, with stronger floors at closer distances.

Distance and velocity confidence are not global score multipliers. They reduce unreliable sub-terms and feed `observation_quality`, which controls how quickly the display-level stabilizer upgrades box color.

### Risk Logging

For debugging risk decisions frame by frame:

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --no-display --risk-log-csv D:\path\risk_log.csv --max-frames 300
```

The CSV includes frame index, track ID, class, detection confidence, observation quality, distance components, distance/velocity confidence, quality flags, ground position, velocity, ego-motion magnitude, radial closing speed, trajectory distance, TTC, DRAC, motion pattern, raw risk score/level, displayed risk score/level, risk term breakdown (`trajectory_risk`, `ttc_risk`, `drac_risk`, `closing_risk`, `static_obstacle_risk`), and stabilizer diagnostics (`stabilizer_pending_level`, `stabilizer_pending_count`, `stabilizer_required_frames`, `stabilizer_reason`).

### Risk Model Tuning

Start with calibration before changing risk thresholds. If distances are biased, fix `camera_matrix`, `camera_height_m`, `camera_pitch_deg`, or `distance_scale` first. If velocity is noisy, check `qV`, ego-motion flags, lighting, `--ego-motion-mode`, `--ego-motion-every-n`, and `--distance-smoothing`. Use `--risk-log-csv` to compare raw risk against displayed risk; if raw risk is correct but colors lag, inspect `stabilizer_reason` and `stabilizer_required_frames`. If raw risk itself is wrong, inspect `TRAJ`, `TTC`, `motion_pattern`, `distance_confidence`, `velocity_confidence`, and the risk term breakdown.

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
- Velocity is the difference between consecutive ground-plane positions for the same stable track ID.

The numbers are useful for early algorithm testing, but they are not final safety-grade measurements. Accurate distance/speed needs careful camera calibration and, in a later system stage, validation against additional sensors or measured ground truth.

## Tests

```powershell
cd D:\mywork\code\embedded-contest-project\06_software\vision_obstacle_tracker
py -m unittest discover -s tests -v
```
