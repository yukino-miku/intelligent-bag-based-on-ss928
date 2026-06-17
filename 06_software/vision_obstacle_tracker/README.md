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
py vision_obstacle_tracker.py --source camera --runtime-profile balanced
py vision_obstacle_tracker.py --source camera --runtime-profile quality
```

`realtime` requests `960x540`, `imgsz=512`, `conf=0.03`, and `max_det=50`; `balanced` requests `1280x720`, `imgsz=1024`, `conf=0.02`, and `max_det=50`; `quality` requests `1920x1080`, `imgsz=1024`, `conf=0.02`, and `max_det=50`. Explicit `--width`, `--height`, `--imgsz`, `--conf`, and `--max-det` values override the selected profile.

For better CPU inference speed on supported Intel/CPU systems, export the YOLO model to OpenVINO and reload the exported model:

```powershell
py -m pip install openvino
py vision_obstacle_tracker.py --source camera --export-openvino
```

The first `--export-openvino` run creates an OpenVINO model folder beside the original YOLO weights. Later runs can use that exported folder directly with `--model`.

If you need to show every COCO class instead of only traffic-related targets:

```powershell
py vision_obstacle_tracker.py --source camera --target-classes all
```

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

For faster CPU processing:

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --imgsz 416
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --imgsz 320
```

Calibration settings:

```powershell
--camera-height 1.2 --camera-pitch 5 --fov 120 --fov-type diagonal
```

Distance and speed tuning:

```powershell
py vision_obstacle_tracker.py --source camera --distance-mode fused --size-weight 0.75
py vision_obstacle_tracker.py --source camera --distance-scale 1.25 --speed-scale 1.25
py vision_obstacle_tracker.py --source camera --camera-pitch 3
```

If measured distance is consistently too small, first lower `--camera-pitch` or raise `--distance-scale`. If distance jitters, lower `--distance-smoothing` toward `0.25`; if speed reacts too slowly, raise it toward `0.6`. `--distance-mode size` uses vehicle/bicycle typical dimensions only, while `--distance-mode ground` uses only the ground-plane projection.

Optional low-light enhancement:

```powershell
py vision_obstacle_tracker.py --source camera --enhance auto
py vision_obstacle_tracker.py --source camera --enhance clahe
py vision_obstacle_tracker.py --source camera --enhance off
```

## Risk Warning Overlay

Each tracked target now displays `RiskScore`, warning level, TTC, and trajectory distance (`TRAJ`) in the box label. Box colors are:

```text
SAFE: green
ATTENTION: yellow
CAUTION: orange-yellow
DANGER: orange-red
EMERGENCY: red
```

To suppress one-frame warning flashes from bad distance or velocity estimates, box color uses a display-level stabilizer: the same track must remain non-SAFE for 3 consecutive processed frames before the box changes to a warning color. A SAFE frame resets that confirmation count.

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
```

Vehicle risk multipliers are applied after the weighted average and before the final clamp:

```text
bicycle: 0.85
motorcycle: 0.95
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

Closing speed is now radial closing speed, computed along the actual line from the camera wearer to the target. A target moving sideways with only a small negative `vz` is no longer treated as strongly closing unless its full motion vector points toward the wearer.

Detection confidence is used only by YOLO/tracking. It is not multiplied into the warning score, because a weak detection can still describe a real obstacle and should not create or suppress risk by itself.

If `vz >= 0`, the target is treated as SAFE regardless of distance. Trajectory distance is computed from the target's current ground position and velocity as the distance from the origin to that motion line: `abs(x * vz - z * vx) / sqrt(vx^2 + vz^2)`. If speed is too close to zero, the current ground distance is used instead.

Hard safety thresholds are applied before scoring: targets are SAFE when `TTC > 5.0s`; bicycles are SAFE when `TRAJ > 1.5m`; motor vehicles (`car`, `motorcycle`, `truck`, `bus`) are SAFE when `TRAJ > 3.0m`. If the target remains inside those hard safety thresholds, the score is a weighted average of trajectory-distance risk, TTC risk, DRAC risk, and radial-closing-speed risk, then multiplied by the vehicle risk multiplier. Trajectory-distance risk uses a saturating power curve, `1 - (TRAJ / safe_distance)^2`. TTC risk also uses a saturating power curve: `1 - ((TTC - 1.5) / (5.0 - 1.5))^2` for `1.5s < TTC < 5.0s`, with `TTC <= 1.5s` saturated at `1.0` and `TTC >= 5.0s` contributing `0.0`. No separate hard-boost or cross-frame danger/emergency hold is applied.

Overlay warning colors use the latest four raw frames for the same stable track. Once four frames are available, the display logic chooses the three closest scores among those four frames, then uses the lowest score of that closest trio as the displayed `RiskScore`; the displayed color is chosen from that score. For example, `0.50, 0.80, 0.55, 0.54` displays ATTENTION from the `0.50/0.54/0.55` trio, while `0.10, 0.90, 0.91, 0.89` displays EMERGENCY from the `0.89/0.90/0.91` trio. If two trios are equally close, the higher trio is used. Emergency red requires the closest-trio minimum score to reach `0.80`; there are no separate hard-boost rules.

If live FPS stays low at every requested resolution, the camera delivery path is the limit rather than YOLO. In that case, check lighting, exposure, and the camera driver settings; reducing resolution will not help until the camera actually supplies frames faster. A common cause is auto exposure in a dim scene lowering the camera to about 5-6 FPS.

## Display Controls

- `q` or `Esc`: exit
- `Space`: pause/resume

## Distance And Speed Limits

This first version uses a single-camera ground-plane approximation:

- The bottom center of each detection box is projected onto a flat ground plane.
- Distance depends on camera height, pitch, field of view, and detection box quality.
- Velocity is the difference between consecutive ground-plane positions for the same stable track ID.

The numbers are useful for early algorithm testing, but they are not final safety-grade measurements. Accurate distance/speed needs careful camera calibration and should later be fused with radar.

## Tests

```powershell
cd D:\mywork\code\embedded-contest-project\06_software\vision_obstacle_tracker
py -m unittest discover -s tests -v
```
