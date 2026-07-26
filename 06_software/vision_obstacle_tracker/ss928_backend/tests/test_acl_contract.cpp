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

int main() {
    std::string error;
    assert(validate_factory_yolov8_contract({input_info()}, {output_info()}, &error));

    ModelTensorInfo bad_input = input_info();
    bad_input.bytes--;
    assert(!validate_factory_yolov8_contract({bad_input}, {output_info()}, &error));
    assert(error.find("614400") != std::string::npos);

    ModelTensorInfo bad_output = output_info();
    bad_output.dims = {1, 8400, 84};
    assert(!validate_factory_yolov8_contract({input_info()}, {bad_output}, &error));
    assert(error.find("[1,84,8400]") != std::string::npos);

    assert(!validate_factory_yolov8_contract({}, {output_info()}, &error));
    assert(!validate_factory_yolov8_contract({input_info()}, {}, &error));
    std::cout << "ACL model contract tests passed\n";
    return 0;
}
