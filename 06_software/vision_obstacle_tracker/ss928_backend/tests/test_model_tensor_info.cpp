#include "model_tensor_info.h"

#include <cstdio>
#include <string>
#include <vector>

namespace {

int failures = 0;

void expect_equal(const std::string &expected, const std::string &actual, const char *label) {
    if (expected != actual) {
        std::fprintf(stderr, "%s: expected [%s], got [%s]\n", label, expected.c_str(), actual.c_str());
        ++failures;
    }
}

}  // namespace

int main() {
    expect_equal("FLOAT32", acl_dtype_name(0), "float dtype");
    expect_equal("UINT8", acl_dtype_name(4), "uint8 dtype");
    expect_equal("UNKNOWN(99)", acl_dtype_name(99), "unknown dtype");
    expect_equal("NCHW", acl_format_name(0), "nchw format");
    expect_equal("ND", acl_format_name(2), "nd format");
    expect_equal("[1,84,8400]", dims_json(std::vector<long long>{1, 84, 8400}), "dims json");
    expect_equal("input\\\"0\\\\nv12", json_escape("input\"0\\nv12"), "json escape");

    ModelTensorInfo tensor;
    tensor.name = "images";
    tensor.dtype = 4;
    tensor.format = 1;
    tensor.dims = {1, 640, 640, 3};
    tensor.bytes = 614400;
    expect_equal(
        "{\"index\":0,\"name\":\"images\",\"dtype\":\"UINT8\",\"dtype_code\":4,"
        "\"format\":\"NHWC\",\"format_code\":1,\"dims\":[1,640,640,3],\"bytes\":614400}",
        tensor_json(tensor, 0),
        "tensor json"
    );

    if (failures != 0) {
        std::fprintf(stderr, "%d model tensor info test failure(s)\n", failures);
        return 1;
    }
    std::printf("model tensor info tests passed\n");
    return 0;
}
