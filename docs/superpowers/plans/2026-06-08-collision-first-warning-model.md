# Collision-First Warning Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make warnings prioritize predicted collision geometry over raw distance, trigger early for true head-on threats, avoid red warnings for near lateral passes, and add a realtime runtime profile aimed at higher FPS.

**Architecture:** Keep deterministic risk behavior inside `risk_model.py`, runtime defaults inside `vision_obstacle_tracker.py`, and regression scenarios in unit tests. The model uses CPA/time-to-CPA/TTC/DRAC gates for severity, caps severity for near-miss paths, and holds severe warnings briefly after one risky frame.

**Tech Stack:** Python 3.13, unittest, Ultralytics YOLO, OpenCV, BoT-SORT tracker config.

---

### Tasks

- [ ] Write red tests for a 3.5m/s head-on bicycle becoming emergency when collision geometry is clear.
- [ ] Write red tests for a 3.3m/s bicycle passing at about 1.5m being capped at CAUTION.
- [ ] Write red tests for one-frame emergency persistence on the same stable track.
- [ ] Write red tests for realtime-oriented default runtime profile.
- [ ] Implement collision-first severity gates using CPA, time-to-CPA, TTC, and DRAC.
- [ ] Implement high-risk hold in `RiskModel.assess`.
- [ ] Add `--runtime-profile realtime|balanced|quality` and profile-based defaults.
- [ ] Lower tracker association thresholds slightly for weak fast bicycle detections.
- [ ] Update README and verify with full unit tests and compile check.
