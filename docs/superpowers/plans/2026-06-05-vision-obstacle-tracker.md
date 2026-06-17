# Vision Obstacle Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a PC-side prototype that reads the current USB camera or a recorded video, runs YOLO object tracking, estimates object distance and velocity, and visualizes the result in real time.

**Architecture:** Keep camera geometry, per-track speed estimation, YOLO/OpenCV runtime glue, and UI drawing separate. Tests cover the deterministic geometry and tracking logic; live camera/model behavior is verified manually with real media.

**Tech Stack:** Python 3.13, OpenCV, Ultralytics YOLO, ByteTrack, NumPy, unittest.

---

### File Structure

- Create `06_software/vision_obstacle_tracker/calibration.py`: camera configuration and pixel-to-ground distance estimation.
- Create `06_software/vision_obstacle_tracker/vision_core.py`: class filtering, per-track distance/speed state, and overlay label formatting.
- Create `06_software/vision_obstacle_tracker/vision_obstacle_tracker.py`: CLI app for `--source camera` and `--source video`.
- Create `06_software/vision_obstacle_tracker/requirements.txt`: Python dependencies.
- Create `06_software/vision_obstacle_tracker/README.md`: install, camera, video-test, calibration, and limitations.
- Create `06_software/vision_obstacle_tracker/tests/test_calibration.py`: camera geometry tests.
- Create `06_software/vision_obstacle_tracker/tests/test_vision_core.py`: track velocity tests.

### Task 1: Camera Geometry

- [ ] Write failing tests for ground-point estimation: center-bottom pixel returns a finite forward distance, pixels above the horizon return `None`, and lower pixels are closer than higher pixels.
- [ ] Implement `CameraCalibration`, `GroundPoint`, and `pixel_to_ground`.
- [ ] Run `py -m unittest discover -s tests -v` and verify tests pass.

### Task 2: Tracking State

- [ ] Write failing tests for speed estimation: the first observation has zero speed, later movement over known time produces `vx`, `vz`, and scalar speed, and invalid/no-ground observations preserve a displayable target without speed.
- [ ] Implement `DetectionObservation`, `TrackedObject`, `TrackState`, and `format_overlay_label`.
- [ ] Run the unit tests and verify they pass.

### Task 3: Runtime App

- [ ] Implement CLI arguments: `--source camera|video`, `--video`, `--camera-index`, `--width`, `--height`, `--fps`, `--model`, `--conf`, `--imgsz`, `--tracker`, and calibration options.
- [ ] Implement camera input with OpenCV DirectShow and video-file input with OpenCV.
- [ ] Use Ultralytics `YOLO.track(..., persist=True)` per frame so the same processing path handles camera and video.
- [ ] Draw boxes, track IDs, class names, confidence, distance, `vx/vz`, and speed on each frame.
- [ ] Add key controls: `q`/`Esc` exits, `Space` pauses video playback.

### Task 4: Dependencies and Verification

- [ ] Install dependencies from `requirements.txt`.
- [ ] Run unit tests.
- [ ] Run a short video-file inference with the newest file in `08_media/camera_data`.
- [ ] Launch the camera path long enough to confirm it opens the USB camera and displays the visualization window.
- [ ] Update `00_admin/project-log.md` with the new tool, commands, and limitations.
