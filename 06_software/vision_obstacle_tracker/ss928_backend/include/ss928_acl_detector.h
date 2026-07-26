#ifndef SS928_ACL_DETECTOR_H
#define SS928_ACL_DETECTOR_H

#include "model_tensor_info.h"

#include <cstddef>
#include <memory>
#include <string>
#include <vector>

bool validate_factory_yolov8_contract(
    const std::vector<ModelTensorInfo> &inputs,
    const std::vector<ModelTensorInfo> &outputs,
    std::string *error);

struct AclInferenceResult {
    const float *output = nullptr;
    std::size_t output_elements = 0;
    std::vector<long long> output_dims;
    double inference_ms = 0.0;
};

class Ss928AclDetector {
public:
    Ss928AclDetector();
    ~Ss928AclDetector();
    Ss928AclDetector(const Ss928AclDetector &) = delete;
    Ss928AclDetector &operator=(const Ss928AclDetector &) = delete;

    bool initialize(const std::string &model_path, int device_id, std::string *error);
    bool infer(const unsigned char *nv12, std::size_t bytes, AclInferenceResult *result, std::string *error);
    void shutdown();
    bool initialized() const;
    std::size_t input_bytes() const;
    const std::vector<ModelTensorInfo> &inputs() const;
    const std::vector<ModelTensorInfo> &outputs() const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

#endif
