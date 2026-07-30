#include "ss928_acl_detector.h"

#include <cassert>
#include <iostream>

static ModelTensorInfo input_info() {
    ModelTensorInfo value;
    value.name = "images";
    value.dtype = 4;
    value.format = 1;
    value.dims = {1, 960, 640, 1};
    value.bytes = 614400;
    return value;
}

static ModelTensorInfo output_info() {
    ModelTensorInfo value;
    value.name = "Concat_254:0:output0";
    value.dtype = 0;
    value.format = 2;
    value.dims = {1, 84, 8400};
    value.bytes = 2822400;
    return value;
}

static ModelTensorInfo rgb_input(int dtype) {
    ModelTensorInfo value;
    value.name = "images";
    value.dtype = dtype;
    value.format = 0;
    value.dims = {1, 3, 640, 640};
    value.bytes = dtype == 0 ? 4915200 : 1228800;
    return value;
}

int main() {
    std::string error;
    ModelInputKind kind = ModelInputKind::RGB_PLANAR_FLOAT32;
    assert(validate_yolo_detection_contract({input_info()}, {output_info()}, &kind, &error));
    assert(kind == ModelInputKind::NV12_UINT8);
    assert(validate_yolo_detection_contract({rgb_input(4)}, {output_info()}, &kind, &error));
    assert(kind == ModelInputKind::RGB_PLANAR_UINT8);
    assert(validate_yolo_detection_contract({rgb_input(0)}, {output_info()}, &kind, &error));
    assert(kind == ModelInputKind::RGB_PLANAR_FLOAT32);

    ModelTensorInfo bad_input = input_info();
    bad_input.bytes--;
    assert(!validate_yolo_detection_contract({bad_input}, {output_info()}, &kind, &error));
    assert(error.find("RGB_PLANAR") != std::string::npos);

    ModelTensorInfo bad_output = output_info();
    bad_output.dims = {1, 8400, 84};
    assert(!validate_yolo_detection_contract({input_info()}, {bad_output}, &kind, &error));
    assert(error.find("[1,84,8400]") != std::string::npos);

    assert(!validate_yolo_detection_contract({}, {output_info()}, &kind, &error));
    assert(!validate_yolo_detection_contract({input_info()}, {}, &kind, &error));
    std::cout << "ACL model contract tests passed\n";
    return 0;
}
