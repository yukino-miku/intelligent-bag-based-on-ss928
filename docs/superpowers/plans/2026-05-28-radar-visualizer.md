# Radar Visualizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a PC-side Python tool that reads the 60GHz mmWave radar UART stream, decodes BSD target reports, evaluates obstacle risk, and displays a live `±40°` radar-sector view.

**Architecture:** Keep protocol parsing, risk evaluation, serial IO, and GUI rendering in separate files. Parser and risk logic are covered by unit tests; serial and GUI stay thin and manually testable with real hardware.

**Tech Stack:** Python 3, stdlib `tkinter`, optional `pyserial`, stdlib `unittest`.

---

### File Structure

- Create `06_software/radar_visualizer/radar_protocol.py`: streaming parser for `0x5A` active report frames and `TYPE=0x07` BSD target lists.
- Create `06_software/radar_visualizer/risk.py`: area classification, risk level selection, and reminder action text.
- Create `06_software/radar_visualizer/radar_visualizer.py`: tkinter GUI, serial reader thread, demo mode.
- Create `06_software/radar_visualizer/README.md`: wiring, install, run, and test instructions.
- Create `06_software/radar_visualizer/tests/test_radar_protocol.py`: parser tests.
- Create `06_software/radar_visualizer/tests/test_risk.py`: risk tests.

### Task 1: Parser Tests

**Files:**
- Create: `06_software/radar_visualizer/tests/test_radar_protocol.py`
- Later create: `06_software/radar_visualizer/radar_protocol.py`

- [ ] **Step 1: Write failing tests**

Test that the parser ignores noise, waits for incomplete frames, verifies checksum, and decodes a `TYPE=0x07` report containing two targets.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest discover -s 06_software/radar_visualizer/tests -v`

Expected: import failure for `radar_protocol`.

- [ ] **Step 3: Implement minimal parser**

Implement dataclasses `RadarTarget`, `RadarReport` and class `RadarStreamParser.feed(data: bytes) -> list[RadarReport]`.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m unittest discover -s 06_software/radar_visualizer/tests -v`

Expected: parser tests pass.

### Task 2: Risk Tests

**Files:**
- Create: `06_software/radar_visualizer/tests/test_risk.py`
- Later create: `06_software/radar_visualizer/risk.py`

- [ ] **Step 1: Write failing tests**

Test angle-to-area mapping, distance/velocity risk thresholds, and highest-risk selection.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest discover -s 06_software/radar_visualizer/tests -v`

Expected: import failure for `risk`.

- [ ] **Step 3: Implement minimal risk evaluator**

Implement `classify_area`, `evaluate_target`, and `summarize_targets`.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m unittest discover -s 06_software/radar_visualizer/tests -v`

Expected: all tests pass.

### Task 3: GUI and Serial Shell

**Files:**
- Create: `06_software/radar_visualizer/radar_visualizer.py`
- Create: `06_software/radar_visualizer/README.md`

- [ ] **Step 1: Implement GUI using tested parser/risk APIs**

Build a tkinter canvas that draws `±40°` field of view, range arcs, target dots, labels, and a status panel.

- [ ] **Step 2: Add serial and demo modes**

Use `pyserial` only when a COM port is supplied. Provide `--demo` mode with synthetic moving targets so the GUI can be verified without hardware.

- [ ] **Step 3: Document wiring and commands**

Document USB-TTL wiring, `921600 8N1`, pyserial install, GUI commands, and official upper-computer verification flow.

- [ ] **Step 4: Run tests and import checks**

Run: `python -m unittest discover -s 06_software/radar_visualizer/tests -v`

Expected: all tests pass.
