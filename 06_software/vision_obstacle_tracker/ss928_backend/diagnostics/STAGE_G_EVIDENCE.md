# Stage G evidence: fixed-input raw-tensor isolation

Date: 2026-07-20

## Result

The zero-detection condition first exists in the factory OM's raw class
scores.  It is not introduced by the current ACL memory path and is not
introduced by YOLOv8 decode, target filtering, coordinate restoration, or
NMS.

For the one locked, contract-valid bus image, the official-SDK reference ACL
path and the current ACL wrapper produce bit-for-bit identical output.  That
output contains no class score at or above 0.25; its highest class score is
0.035400390625 and the bus-class maximum is 0.00014317035675048828.

Lowering the threshold is not a valid fix: the highest raw class is
`toothbrush`, not `bus`.

## Locked input

- Source: `data/test_source.jpg`, 546x413, obvious red double-decker bus.
- Source SHA256:
  `e4c4dd62995cbe30501798f86fcf5973c7abe3ff9f7711fdb72c6d1f7f304484`.
- Only raw input: `data/test_input.nv12`, 614400 bytes.
- Raw SHA256:
  `76314d959c8e4dcd6a1d2893c9fad3013f31805caadcdcbc58caeda220a76e0a`.
- Head 32 bytes: 32 copies of `72` hex; tail 32 bytes: 32 copies of
  `80` hex.
- Y: offset 0, 409600 bytes; UV: offset 409600, 204800 bytes.
- Y stride 640, UV stride 640; there is no per-row padding.
- Letterbox: 546x413 -> 640x484, pad left/right 0, pad top/bottom 78.

`artifacts/locked_input_validation.json` reconstructs RGB with the exact CSC
matrix read from the OM.  Against `data/test_letterbox.ppm`, the reconstruction
has mean absolute error 0.701794/255 and PSNR 44.4872 dB.  All top/bottom
padding samples are Y=114 and UV=128.  This validates the byte stream without
generating or inferring a second input.

## Board-queried OM contract

Model: `/opt/sample/yolov8/yolov8n.om`, 7932770 bytes, SHA256
`7010d928c2ce9675ea38b6ee353f1c4fcd4ec648a335d3735d85f2e0313d030b`.
The V2.0.2.2 and V2.0.2.3 repository copies have the same size and SHA256.

- Inputs: 1.
- Input 0: `images`, UINT8, NHWC, `[1,960,640,1]`, 614400 bytes.
- AIPP type: static.
- AIPP input: YUV420SP_U8; `rbuvSwapSwitch=0` means NV12/UV, not NV21/VU.
- Source image: width 640, height 640.  YUV420 dimensions must be even; both
  are.  The descriptor and exact byte count fix the dense stride at 640, with
  no extra alignment bytes in the file contract.
- CSC: enabled; matrix
  `[256,0,359; 256,-88,-183; 256,454,0]`, input bias `[0,128,128]`.
  These are Huawei's BT.601 wide/full (also JPEG full-range) YUV-to-RGB
  coefficients, not BT.709 and not limited/narrow coefficients.
- Output bias: `[16,128,128]`; this field is for RGB-to-YUV and is not used by
  this YUV-to-RGB conversion.
- Channel swaps: `rbuv=0`, `ax=0`; single-line mode 0.
- Crop: disabled; origin 0,0; stored crop size 0x0.
- Resize: disabled; stored output 0x0.
- Padding: disabled; left/right/top/bottom all 0.
- Mean `[0,0,0,0]`; min `[0,0,0,0]`; variance reciprocal
  `[1/255,1/255,1/255,1]`.
- AIPP network-side source: NCHW FP32 `[1,3,640,640]`, 4915200 bytes.
- Outputs: 1.
- Output 0: `Concat_254:0:output0`, FLOAT32, ND, `[1,84,8400]`,
  2822400 bytes.

The complete machine-readable query is `artifacts/model_desc_full.json`.

## Raw-output comparison

Both programs opened the same board path
`/root/ss928_yolov8_vot_diag/test_input.nv12`; neither decoded an image nor
performed resize, letterbox, color conversion, confidence filtering, box
conversion, or NMS.

| Test | Reference runner | Current runner | Same? | Conclusion |
|---|---|---|---|---|
| Model | Factory OM SHA256 `7010d928...030b` | Same path and hash | Yes | Same immutable model |
| Input | 614400 bytes, SHA256 `76314d95...6e0a` | Same file path and bytes | Yes | No preprocessing divergence |
| Input descriptor | UINT8 NHWC `[1,960,640,1]` | Contract-checked same | Yes | Exact 614400-byte binding |
| Output descriptor | FP32 ND `[1,84,8400]` | Same | Yes | One 2822400-byte tensor |
| Output SHA256 | `c843d68e...5298` | `c843d68e...5298` | Yes | Bit-for-bit identical |
| Min / max / mean | 0.0000152588 / 637.5 / 9.22046913596 | Same | Yes | Raw tensor statistics match |
| First 16 floats | `2.82421875, 21.34375, 31.03125, ...` | Same | Yes | Ordering and values match |
| Nonzero / nonfinite | 705600 / 0 | 705600 / 0 | Yes | Complete valid output |
| Element error | Baseline | 0 different; max abs error 0 | Yes | Stop ACL/MMZ investigation |
| YOLO layout | Official `[84,8400]` channel-first | Same descriptor-based indexing | Yes | No transpose required |
| Confidence before NMS | 0 proposals at 0.25 | 0 proposals at 0.25 | Yes | Zero already exists in raw scores |

## YOLOv8 postprocess audit

- V2.0.2.2 official `yolov8.cpp` indexes
  `src[(class+4)*8400+anchor]`, uses 4+80 channels, applies no sigmoid and uses
  the class probability directly.
- The current decoder selects channel-first for the real descriptor and uses
  the same `xywh` and class-score interpretation.
- Interpreting the same bytes as `[1,8400,84]` produces 32000 supposed class
  scores above 1, up to 637.5; that layout is invalid.
- Real class-score range is 0.0000152588 to 0.0354004, with no negative,
  above-one, NaN, or Inf values.  Applying sigmoid again would move every
  score to approximately 0.5 and is incorrect.
- At confidence 0.25 there are zero proposals before the configured target
  class filter.  Therefore class filtering is not the cause.
- `xywh -> xyxy`, letterbox restoration and NMS execute only after confidence
  admission; none can create the observed zero.
- The current decoder's synthetic channel-first, channel-last, coordinate
  restoration and class-aware NMS tests pass.

The complete statistics are in `artifacts/postprocess_audit.json`.

## Implementation and logs

- Reference source: `diagnostics/reference_raw_runner.cpp`, based directly on
  V2.0.2.2 `sample_npu_process.c`/`sample_npu_model.c` ordinary
  `aclrtMalloc` path.
- Current source: `diagnostics/current_raw_runner.cpp`, calls only
  `Ss928AclDetector`; it does not call YOLO decode or the VOT pipeline.
- Board evidence: `/root/ss928_yolov8_vot_diag/`.
- Repository evidence: `work/ss928_yolov8_vot/diagnostics/artifacts/`.
- WSL build target: `make raw_diagnostics`.
- Both binaries are ELF64 AArch64 PIE executables and neither has a
  `libgomp.so` dependency.

No USB camera was attached or used.  No factory OM, production inference
path, NPU runtime, network configuration, or board startup configuration was
modified.
