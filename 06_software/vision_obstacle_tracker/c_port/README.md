# Vision Obstacle Tracker C Port

This directory is an isolated C port of the Python `vision_obstacle_tracker` core. It does not modify any Python files in the parent directory.

## Scope

Implemented in C99:

- runtime profile defaults and command-line option parsing
- camera calibration and ground/size/fused distance estimation
- stable track ID reassociation
- per-track distance smoothing and velocity estimation
- risk scoring, including `vz >= 0` forced SAFE
- trajectory-distance power risk curve
- display-level 3-frame warning stabilization
- warning names and BGR colors
- MJPEG byte stream frame parser

Runnable live/video backend:

- `src/vision_obstacle_tracker_live.cpp`
- OpenCV camera/video/display/output
- ONNX Runtime YOLO inference from exported ONNX models
- YOLO output decode, target-class filter, NMS, and lightweight IoU raw tracker
- bridge into the C99 core for stable IDs, speed, risk, and 3-frame warning stabilization

The C constants follow the current Python source files and Python tests. If README text in the parent folder disagrees with source code, the source code is treated as authoritative.

## Build Core

From this directory:

```powershell
gcc -std=c99 -Wall -Wextra -Werror -Iinclude tests\test_core.c src\vot.c -lm -o build\test_core.exe
.\build\test_core.exe

gcc -std=c99 -Wall -Wextra -Werror -Iinclude src\vision_obstacle_tracker_c.c src\vot.c -lm -o build\vision_obstacle_tracker_c.exe
.\build\vision_obstacle_tracker_c.exe --print-config
```

If `make` is available:

```powershell
make all
make test
```

## Backend Dependency Setup

The local backend dependencies are installed under `third_party` and can be reproduced with:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_backend.ps1
powershell -ExecutionPolicy Bypass -File .\setup_backend.ps1 -InstallBuildTools
```

Installed paths:

```text
third_party/downloads/onnxruntime-win-x64-1.26.0.zip
third_party/onnxruntime/onnxruntime-win-x64-1.26.0
third_party/downloads/opencv-4.13.0-windows.exe
third_party/opencv
```

The OpenCV package is the official Windows `vc16` build, so a backend that links `opencv_world4130.lib` must be built with MSVC, not the MinGW GCC currently used for the dependency-free C core. On this machine, Visual Studio Build Tools 2022 with VC tools was installed for that purpose. Open a VC build environment with:

```powershell
cmd /c '"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" && cl'
```

Check the installed dependency files with:

```powershell
.\build\vision_obstacle_tracker_live.exe --backend-status
```

## Runtime Configuration

The dependency-free C entrypoint accepts the same core option names as the Python program. Examples:

```powershell
.\build\vision_obstacle_tracker_c.exe --print-config
.\build\vision_obstacle_tracker_c.exe --print-config --runtime-profile realtime --width 1920 --height 1080 --imgsz 864
.\build\vision_obstacle_tracker_c.exe --backend-status
```

The live/video backend is built with MSVC, OpenCV, and ONNX Runtime:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_live_msvc.ps1
.\build\vision_obstacle_tracker_live.exe --backend-status
```

The default Python model `yolo11n.pt` must be exported to ONNX once. The C backend uses a static ONNX input and requires the ONNX input size to match `--imgsz`:

```powershell
powershell -ExecutionPolicy Bypass -File .\export_yolo_onnx.ps1
```

Live camera:

```powershell
cd D:\mywork\code\embedded-contest-project\06_software\vision_obstacle_tracker\c_port
.\build\vision_obstacle_tracker_live.exe --source camera --runtime-profile realtime --camera-index 1
```

On this machine the working camera is index `0`; the live backend will try index `0` automatically if the requested index fails. You can still make it explicit:

```powershell
.\build\vision_obstacle_tracker_live.exe --source camera --runtime-profile realtime --camera-index 0
```

Recorded video:

```powershell
.\build\vision_obstacle_tracker_live.exe --source video --video D:\path\input.mp4
```

Save an overlay video:

```powershell
.\build\vision_obstacle_tracker_live.exe --source video --video D:\path\input.mp4 --video-every-frame --no-display --save-output D:\path\overlay_c.mp4
```

Default values match `vision_obstacle_tracker.py`:

```text
source=camera
camera_backend=ffmpeg
runtime_profile=balanced
width=1280
height=720
tracker=vehicle_botsort.yaml
imgsz=1024
conf=0.02
max_det=50
camera_height=1.2
fov=120 diagonal
camera_pitch=5
distance_mode=fused
distance_smoothing=0.35
max_speed=40.0
```

## YOLO And Video Backend

The runnable C-side live/video backend is `src/vision_obstacle_tracker_live.cpp`. It uses OpenCV for camera/video/display/output and ONNX Runtime for YOLO inference, then feeds detections into the C99 core in `src/vot.c`.

The Python version relies on `ultralytics` to load `yolo11n.pt` and run BoT-SORT. The C live backend uses exported ONNX weights and a lightweight IoU tracker before the same C stable-ID layer. That means the post-detection distance, speed, risk, and 3-frame warning stabilization logic is shared with the C core, while the raw tracker is not a byte-for-byte BoT-SORT port.

Main backend flow:

- export `yolo11n.pt` to `models/yolo11n_imgsz512.onnx` and `models/yolo11n_imgsz1024.onnx`
- run detection with ONNX Runtime
- decode YOLO output, filter target classes, and run NMS
- keep short-lived raw IDs with a simple IoU tracker
- feed detections into the C core as `VotDetectionObservation`
- keep the post-detection path unchanged: stable ID, `TrackState`, `vot_assess_collision_risk`, then `vot_risk_warning_stabilize_one`

## Source Mapping

| Python file | C port |
| --- | --- |
| `calibration.py` | `src/vot.c` calibration section |
| `vision_core.py` | `src/vot.c` tracking section |
| `risk_model.py` | `src/vot.c` risk section |
| `camera_source.py` | `src/vot.c` MJPEG parser section |
| `vision_obstacle_tracker.py` runtime/overlay helpers | `src/vot.c`, `src/vision_obstacle_tracker_c.c` |
| Python tests | `tests/test_core.c` |

## Verification

Run the core tests:

```powershell
cd D:\mywork\code\embedded-contest-project\06_software\vision_obstacle_tracker\c_port
gcc -std=c99 -Wall -Wextra -Werror -Iinclude tests\test_core.c src\vot.c -lm -o build\test_core.exe
.\build\test_core.exe
```

Run the live backend checks:

```powershell
cmd /c '"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" && cl /nologo /EHsc /std:c++17 /W4 /WX /Iinclude tests\test_backend.cpp src\vot_backend.cpp /Fe:build\test_backend.exe && build\test_backend.exe'
powershell -ExecutionPolicy Bypass -File .\build_live_msvc.ps1
.\build\vision_obstacle_tracker_live.exe --backend-status
.\build\vision_obstacle_tracker_live.exe --source video --video D:\path\input.mp4 --runtime-profile realtime --max-frames 3 --no-display --save-output D:\path\c_smoke.mp4
```

Run the original Python tests to ensure the Python version still works:

```powershell
cd D:\mywork\code\embedded-contest-project\06_software\vision_obstacle_tracker
py -m unittest discover -s tests -v
```
