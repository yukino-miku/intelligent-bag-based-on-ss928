# Changelog

This file records GitHub-visible project updates. New functional changes should add a dated entry here before pushing.

## 2026-07-02

- Rebuilt the root GitHub project homepage in `README.md` with install, video input, camera input, OpenVINO, risk logging, output-video saving, profiling, and debugging instructions.
- Added an explicit update rule: future meaningful changes should update the relevant README and this changelog before pushing to GitHub.
- Documented that `08_media/`, `10_archive/`, video files, generated risk logs, build outputs, and large local dependency folders are intentionally excluded from GitHub.
- Recent visual tracker performance updates include YOLO class pre-filtering, ROI top cropping through `--roi-top-ratio`, OpenVINO preference through `--prefer-openvino`, profiling through `--profile`, and preview refresh control through `--display-every-n`.
- Recent visual risk-debug updates include CSV risk logging, runtime profile presets, ego-motion quality reporting, confidence-aware display stabilization, distance quality flags, and clearer risk-term diagnostics.
