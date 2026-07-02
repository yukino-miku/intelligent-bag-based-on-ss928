# Intelligent Bag Based on SS928

This repository contains the local project files for an intelligent backpack prototype based on SS928. The current runnable software focus is the PC-side visual obstacle avoidance prototype under:

```text
06_software/vision_obstacle_tracker
```

Current stage note: the active risk-decision path is vision only. Millimeter-wave radar is not used by the current visual obstacle tracker decisions.

## Current Capabilities

- USB camera and recorded-video input.
- Ultralytics YOLO detection.
- BoT-SORT tracking with stable ID reassociation.
- Monocular ground-plane distance estimation.
- Per-target speed and motion-pattern estimation.
- Risk scoring and colored OpenCV overlay.
- ROI crop before inference to reduce unnecessary upper-frame processing.
- YOLO class pre-filtering for traffic-related targets.
- Optional OpenVINO loading path for CPU inference.
- Runtime profiling for capture, crop, enhancement, ego-motion, inference, risk, drawing, and display/write stages.
- Optional CSV risk log for frame-by-frame debugging.

## Repository Layout

```text
00_admin/       project planning, logs, notes
01_requirements/ requirements and contest interpretation
02_research/    research notes and references
03_design/      system design and architecture
04_hardware/    hardware design files
05_firmware/    embedded firmware area
06_software/    PC-side software and tools
07_tests/       test plans and validation records
08_media/       local images/videos, not uploaded to GitHub
09_deliverables/final reports, slides, demo materials
10_archive/     old or discarded files, not uploaded to GitHub
```

Large local media and archive folders are intentionally excluded from GitHub:

```text
08_media/
10_archive/
*.mp4, *.avi, *.mov, *.mkv, ...
risk_log.csv
*_risk_log.csv
```

## Install The Visual Obstacle Tracker

```powershell
cd D:\mywork\code\embedded-contest-project\06_software\vision_obstacle_tracker
py -m pip install -r requirements.txt
```

Optional CPU acceleration and calibration helpers:

```powershell
py -m pip install openvino
py -m pip install PyYAML
```

The first YOLO run may download model weights if they are not already cached.

## Run A Recorded Video

Basic video detection:

```powershell
cd D:\mywork\code\embedded-contest-project\06_software\vision_obstacle_tracker
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4
```

Recommended CPU demo command:

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --profile
```

Run with existing OpenVINO export if available:

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --prefer-openvino --profile
```

Save an output video with detection boxes:

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --save-output D:\path\overlay.mp4
```

Process every video frame without opening the display window:

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --video-every-frame --no-display --save-output D:\path\overlay_full.mp4
```

## Run A USB Camera

Basic camera detection:

```powershell
cd D:\mywork\code\embedded-contest-project\06_software\vision_obstacle_tracker
py vision_obstacle_tracker.py --source camera
```

Recommended CPU camera test:

```powershell
py vision_obstacle_tracker.py --source camera --runtime-profile cpu_demo --roi-top-ratio 0.20 --profile
```

If the wrong camera opens, change the camera index:

```powershell
py vision_obstacle_tracker.py --source camera --camera-index 0
py vision_obstacle_tracker.py --source camera --camera-index 1
```

If the FFmpeg camera backend fails, try OpenCV camera input:

```powershell
py vision_obstacle_tracker.py --source camera --camera-backend opencv --camera-index 1
```

## OpenVINO CPU Path

Export once:

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --export-openvino
```

Later runs can prefer the exported OpenVINO model:

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --prefer-openvino --profile
```

`--prefer-openvino` only loads an existing OpenVINO export. It does not export automatically. If no export folder exists beside the `.pt` model, the program falls back to the original PyTorch model.

## Risk Debug Log

Write per-frame risk diagnostics to CSV:

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --prefer-openvino --risk-log-csv D:\path\risk_log.csv --profile
```

Useful columns include:

```text
track_id, class_name, distance_m, velocity_x_mps, velocity_z_mps,
radial_closing_speed_mps, trajectory_distance_m, ttc_s, drac_mps2,
motion_pattern, raw_risk_score, raw_risk_level,
display_risk_score, display_risk_level,
trajectory_risk, ttc_risk, drac_risk, closing_risk,
distance_confidence, velocity_confidence, observation_quality,
quality_flags, stabilizer_reason
```

Use this CSV when the box color looks wrong. First check whether `raw_risk_score` is already wrong. If the raw score is reasonable but the displayed level lags, inspect `display_risk_level`, `stabilizer_reason`, and observation quality.

## Performance Debugging

Enable profiling:

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --profile
```

The profile output reports sliding-average stage times:

```text
capture
roi/crop
enhance
ego-motion
infer+track
postprocess
risk
draw
display/write
total
```

How to interpret common bottlenecks:

- `infer+track` high: reduce `--imgsz`, use `--runtime-profile cpu_demo`, try `--roi-top-ratio 0.15` or `0.20`, and try `--prefer-openvino` after exporting.
- `display/write` high: compare `--display-every-n 5` and `--no-display`.
- `draw` high: check whether many boxes or text overlays are being drawn.
- `ego-motion` high: compare `--ego-motion-mode off` or increase `--ego-motion-every-n`.
- Camera FPS low even with small `imgsz`: check lighting, exposure, camera backend, resolution, and camera driver settings.

Suggested comparison commands:

```powershell
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --display-every-n 1 --profile
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --display-every-n 5 --profile
py vision_obstacle_tracker.py --source video --video D:\path\input.mp4 --runtime-profile cpu_demo --roi-top-ratio 0.20 --no-display --profile
```

Expected trend:

```text
--no-display should usually be fastest.
--display-every-n 5 should refresh the window less often, but detection/tracking/risk still run every processed frame.
--display-every-n 1 keeps the original preview behavior.
```

## Important Runtime Parameters

```text
--source camera|video
    Select USB camera input or recorded-video input.

--video D:\path\input.mp4
    Video file path when --source video is used.

--runtime-profile realtime|cpu_demo|balanced|quality
    Preset for resolution, inference image size, confidence, and max detections.

--roi-top-ratio 0.20
    Crop the top 20 percent of the frame before YOLO inference. This reduces sky, ceiling, and upper-building regions. Start with 0.15 or 0.20; too large may miss far targets near the horizon.

--target-classes car,bicycle,motorcycle,bus,truck
    Traffic classes to keep. Use all to keep every YOLO class.

--prefer-openvino
    Prefer an existing OpenVINO export beside the .pt model.

--export-openvino
    Export the YOLO model to OpenVINO format.

--display-every-n 5
    Refresh the OpenCV window every N processed frames. Detection, tracking, risk, and output writing still run normally.

--no-display
    Disable the OpenCV preview window.

--save-output D:\path\overlay.mp4
    Save a video with overlay boxes and labels.

--risk-log-csv D:\path\risk_log.csv
    Save detailed risk calculation diagnostics.

--max-frames 300
    Stop after processing this many frames. Useful for short tests.

--profile
    Print stage timing information about once per second.
```

For the full visual tracker documentation, see:

```text
06_software/vision_obstacle_tracker/README.md
```

## Tests

Run the visual tracker unit tests:

```powershell
cd D:\mywork\code\embedded-contest-project\06_software\vision_obstacle_tracker
py -m unittest discover -s tests -v
```

Compile-check Python files:

```powershell
cd D:\mywork\code\embedded-contest-project\06_software\vision_obstacle_tracker
py -m compileall .
```

## Update And GitHub Documentation Rule

Every meaningful project update should also update GitHub-visible documentation:

1. Update the relevant module README when commands, parameters, or behavior changes.
2. Update this root README when the project homepage, quick start, or debugging workflow changes.
3. Add a dated entry to `CHANGELOG.md` for each uploaded change set.
4. Keep test videos, generated risk logs, archive folders, build outputs, and local dependency folders out of GitHub.

This rule is meant to keep the GitHub project page useful for future testing, debugging, and contest presentation instead of only storing source code.
