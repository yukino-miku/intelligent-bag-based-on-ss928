#!/usr/bin/env python3
"""Validate the ONNX contract required by the SS928 YOLO backend."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


EXPECTED_INPUT_NAME = "images"
EXPECTED_INPUT_SHAPE = (1, 3, 640, 640)
EXPECTED_OUTPUT_SHAPE = (1, 84, 8400)


def _tensor_shape(value_info) -> tuple[int, ...]:
    dimensions = value_info.type.tensor_type.shape.dim
    if any(dimension.dim_param for dimension in dimensions):
        raise ValueError(f"dynamic dimensions are not supported: {value_info.name}")
    return tuple(int(dimension.dim_value) for dimension in dimensions)


def inspect_model(model_path: Path) -> dict[str, object]:
    try:
        import onnx
        from onnx import TensorProto
    except ImportError as exc:
        raise RuntimeError("install the 'onnx' Python package before conversion") from exc

    model = onnx.load(str(model_path), load_external_data=True)
    onnx.checker.check_model(model)
    if len(model.graph.input) != 1:
        raise ValueError(f"expected one model input, got {len(model.graph.input)}")
    if len(model.graph.output) != 1:
        raise ValueError(f"expected one model output, got {len(model.graph.output)}")

    model_input = model.graph.input[0]
    model_output = model.graph.output[0]
    input_shape = _tensor_shape(model_input)
    output_shape = _tensor_shape(model_output)
    input_type = int(model_input.type.tensor_type.elem_type)
    output_type = int(model_output.type.tensor_type.elem_type)

    if model_input.name != EXPECTED_INPUT_NAME:
        raise ValueError(
            f"expected input name {EXPECTED_INPUT_NAME!r}, got {model_input.name!r}"
        )
    if input_shape != EXPECTED_INPUT_SHAPE:
        raise ValueError(f"expected input shape {EXPECTED_INPUT_SHAPE}, got {input_shape}")
    if output_shape != EXPECTED_OUTPUT_SHAPE:
        raise ValueError(f"expected output shape {EXPECTED_OUTPUT_SHAPE}, got {output_shape}")
    if input_type != TensorProto.FLOAT:
        raise ValueError(f"expected FP32 ONNX input, got TensorProto type {input_type}")
    if output_type != TensorProto.FLOAT:
        raise ValueError(f"expected FP32 ONNX output, got TensorProto type {output_type}")

    return {
        "model": str(model_path.resolve()),
        "opset": max(opset.version for opset in model.opset_import),
        "input_name": model_input.name,
        "input_shape": list(input_shape),
        "input_type": "FP32",
        "output_name": model_output.name,
        "output_shape": list(output_shape),
        "output_type": "FP32",
        "contract": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path, help="YOLO11 detection ONNX file")
    args = parser.parse_args()
    if not args.model.is_file():
        parser.error(f"model does not exist: {args.model}")

    try:
        report = inspect_model(args.model)
    except (RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
