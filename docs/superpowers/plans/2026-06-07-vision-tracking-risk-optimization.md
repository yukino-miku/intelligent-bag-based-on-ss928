# Vision Tracking Risk Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve live vehicle tracking continuity, sensitivity, CPU throughput options, and risk accuracy for the vision obstacle tracker.

**Architecture:** Keep deterministic tracking/risk behavior in tested Python modules and keep YOLO/OpenCV runtime glue thin. Use a tuned local BoT-SORT config for moving-camera tracking, a stable-ID layer over Ultralytics track IDs, radial closing speed with CPA/TTC gates for warnings, and an optional OpenVINO export helper without adding SAHI in the first pass.

**Tech Stack:** Python 3.13, unittest, OpenCV, Ultralytics YOLO, BoT-SORT/ByteTrack tracker configs, optional OpenVINO exported model.

---

### File Structure

- Modify `06_software/vision_obstacle_tracker/vision_core.py`: add stable-ID reassociation on top of detector tracker IDs.
- Modify `06_software/vision_obstacle_tracker/risk_model.py`: replace `-vz` closing speed with radial closing speed and gate risk escalation by predicted path.
- Modify `06_software/vision_obstacle_tracker/vision_obstacle_tracker.py`: default to local BoT-SORT config, use stable IDs, add `--export-openvino`.
- Create `06_software/vision_obstacle_tracker/vehicle_botsort.yaml`: tuned tracker config for chest-mounted moving camera.
- Modify tests under `06_software/vision_obstacle_tracker/tests`: red/green coverage for new behavior and aligned runtime defaults.
- Modify `06_software/vision_obstacle_tracker/README.md`: document the new defaults and optional OpenVINO path.

### Tasks

- [ ] Add failing tests for stable ID reassociation after a short tracker-ID switch.
- [ ] Add failing tests for radial closing speed and lower false risk on a lateral pass.
- [ ] Add failing tests for the BoT-SORT default tracker and OpenVINO export option.
- [ ] Implement stable ID reassociation in `vision_core.py`.
- [ ] Implement radial closing speed and CPA-gated emergency behavior in `risk_model.py`.
- [ ] Wire stable IDs, tracker config, and OpenVINO export into `vision_obstacle_tracker.py`.
- [ ] Add `vehicle_botsort.yaml` and update README.
- [ ] Run targeted tests, then full `py -m unittest discover -s tests -v`.
