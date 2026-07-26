#include "ss928_acl_detector.h"

#include <sstream>

namespace {

bool fail_contract(const std::string &message, std::string *error) {
    if (error != nullptr) *error = message;
    return false;
}

}  // namespace

bool validate_factory_yolov8_contract(
    const std::vector<ModelTensorInfo> &inputs,
    const std::vector<ModelTensorInfo> &outputs,
    std::string *error) {
    if (inputs.size() != 1) {
        return fail_contract("factory model must have exactly one input", error);
    }
    if (outputs.size() != 1) {
        return fail_contract("factory model must have exactly one output", error);
    }
    const ModelTensorInfo &input = inputs[0];
    if (input.dtype != 4 || input.bytes != 614400 || input.dims != std::vector<long long>({1, 960, 640, 1})) {
        return fail_contract("factory input must be UINT8 [1,960,640,1], 614400-byte NV12 with static AIPP", error);
    }
    const ModelTensorInfo &output = outputs[0];
    if (output.dtype != 0 || output.bytes != 2822400 || output.dims != std::vector<long long>({1, 84, 8400})) {
        return fail_contract("factory output must be FLOAT32 [1,84,8400], 2822400 bytes", error);
    }
    if (error != nullptr) error->clear();
    return true;
}

#ifndef SS928_ACL_CONTRACT_ONLY

#include "acl.h"

#include <chrono>
#include <cstring>
#include <iostream>

namespace {

const char *acl_detail() {
    const char *value = aclGetRecentErrMsg();
    return value == nullptr ? "" : value;
}

std::vector<long long> copy_dims(const aclmdlIODims &dims) {
    std::vector<long long> result;
    result.reserve(dims.dimCount);
    for (std::size_t i = 0; i < dims.dimCount; ++i) result.push_back(dims.dims[i]);
    return result;
}

bool acl_failure(const char *stage, const char *api, aclError ret,
                 const std::string &model, std::size_t index, std::size_t bytes,
                 std::string *error) {
    std::ostringstream stream;
    stream << "ACL error stage=" << stage << " api=" << api << " ret=" << ret
           << " model=" << model << " index=" << index << " bytes=" << bytes
           << " detail=" << acl_detail();
    if (error != nullptr) *error = stream.str();
    return false;
}

}  // namespace

struct Ss928AclDetector::Impl {
    std::string model_path;
    int device_id = 0;
    bool acl_initialized = false;
    bool device_set = false;
    bool model_loaded = false;
    bool ready = false;
    std::uint32_t model_id = 0;
    void *model_mem = nullptr;
    void *model_weight = nullptr;
    std::size_t model_mem_size = 0;
    std::size_t model_weight_size = 0;
    aclmdlDesc *desc = nullptr;
    aclmdlDataset *input_dataset = nullptr;
    aclmdlDataset *output_dataset = nullptr;
    aclDataBuffer *input_data_buffer = nullptr;
    aclDataBuffer *output_data_buffer = nullptr;
    void *input_buffer = nullptr;
    void *output_buffer = nullptr;
    std::size_t input_size = 0;
    std::size_t output_size = 0;
    std::vector<ModelTensorInfo> input_info;
    std::vector<ModelTensorInfo> output_info;
};

Ss928AclDetector::Ss928AclDetector() : impl_(new Impl) {}
Ss928AclDetector::~Ss928AclDetector() { shutdown(); }

bool Ss928AclDetector::initialize(const std::string &model_path, int device_id, std::string *error) {
    shutdown();
    impl_->model_path = model_path;
    impl_->device_id = device_id;
    aclError ret = aclInit("");
    if (ret != ACL_ERROR_NONE) return acl_failure("init", "aclInit", ret, model_path, 0, 0, error);
    impl_->acl_initialized = true;

    ret = aclrtSetDevice(device_id);
    if (ret != ACL_ERROR_NONE) {
        acl_failure("init", "aclrtSetDevice", ret, model_path, 0, 0, error);
        shutdown();
        return false;
    }
    impl_->device_set = true;
    aclrtRunMode run_mode = ACL_HOST;
    ret = aclrtGetRunMode(&run_mode);
    if (ret != ACL_ERROR_NONE || run_mode != ACL_DEVICE) {
        if (ret == ACL_ERROR_NONE) {
            if (error != nullptr) *error = "ACL error stage=init api=aclrtGetRunMode: board must use ACL_DEVICE mode";
        } else {
            acl_failure("init", "aclrtGetRunMode", ret, model_path, 0, 0, error);
        }
        shutdown();
        return false;
    }

    ret = aclmdlQuerySize(model_path.c_str(), &impl_->model_mem_size, &impl_->model_weight_size);
    if (ret != ACL_ERROR_NONE) {
        acl_failure("query", "aclmdlQuerySize", ret, model_path, 0, 0, error);
        shutdown();
        return false;
    }
    ret = aclrtMalloc(&impl_->model_mem, impl_->model_mem_size, ACL_MEM_MALLOC_HUGE_FIRST);
    if (ret != ACL_ERROR_NONE) {
        acl_failure("allocate", "aclrtMalloc(model_mem)", ret, model_path, 0, impl_->model_mem_size, error);
        shutdown();
        return false;
    }
    ret = aclrtMalloc(&impl_->model_weight, impl_->model_weight_size, ACL_MEM_MALLOC_HUGE_FIRST);
    if (ret != ACL_ERROR_NONE) {
        acl_failure("allocate", "aclrtMalloc(model_weight)", ret, model_path, 0, impl_->model_weight_size, error);
        shutdown();
        return false;
    }
    ret = aclmdlLoadFromFileWithMem(model_path.c_str(), &impl_->model_id,
        impl_->model_mem, impl_->model_mem_size, impl_->model_weight, impl_->model_weight_size);
    if (ret != ACL_ERROR_NONE) {
        acl_failure("load", "aclmdlLoadFromFileWithMem", ret, model_path, 0, 0, error);
        shutdown();
        return false;
    }
    impl_->model_loaded = true;

    impl_->desc = aclmdlCreateDesc();
    if (impl_->desc == nullptr) {
        if (error != nullptr) *error = "ACL error stage=descriptor api=aclmdlCreateDesc ret=null model=" + model_path;
        shutdown();
        return false;
    }
    ret = aclmdlGetDesc(impl_->desc, impl_->model_id);
    if (ret != ACL_ERROR_NONE) {
        acl_failure("descriptor", "aclmdlGetDesc", ret, model_path, 0, 0, error);
        shutdown();
        return false;
    }

    const std::size_t input_count = aclmdlGetNumInputs(impl_->desc);
    const std::size_t output_count = aclmdlGetNumOutputs(impl_->desc);
    for (std::size_t i = 0; i < input_count; ++i) {
        aclmdlIODims dims{};
        ret = aclmdlGetInputDimsV2(impl_->desc, i, &dims);
        if (ret != ACL_ERROR_NONE) {
            acl_failure("descriptor", "aclmdlGetInputDimsV2", ret, model_path, i, 0, error);
            shutdown();
            return false;
        }
        ModelTensorInfo info;
        const char *name = aclmdlGetInputNameByIndex(impl_->desc, i);
        info.name = name == nullptr ? "" : name;
        info.dtype = aclmdlGetInputDataType(impl_->desc, i);
        info.format = aclmdlGetInputFormat(impl_->desc, i);
        info.dims = copy_dims(dims);
        info.bytes = aclmdlGetInputSizeByIndex(impl_->desc, i);
        impl_->input_info.push_back(info);
    }
    for (std::size_t i = 0; i < output_count; ++i) {
        aclmdlIODims dims{};
        ret = aclmdlGetOutputDims(impl_->desc, i, &dims);
        if (ret != ACL_ERROR_NONE) {
            acl_failure("descriptor", "aclmdlGetOutputDims", ret, model_path, i, 0, error);
            shutdown();
            return false;
        }
        ModelTensorInfo info;
        const char *name = aclmdlGetOutputNameByIndex(impl_->desc, i);
        info.name = name == nullptr ? "" : name;
        info.dtype = aclmdlGetOutputDataType(impl_->desc, i);
        info.format = aclmdlGetOutputFormat(impl_->desc, i);
        info.dims = copy_dims(dims);
        info.bytes = aclmdlGetOutputSizeByIndex(impl_->desc, i);
        impl_->output_info.push_back(info);
    }
    if (!validate_factory_yolov8_contract(impl_->input_info, impl_->output_info, error)) {
        shutdown();
        return false;
    }
    impl_->input_size = impl_->input_info[0].bytes;
    impl_->output_size = impl_->output_info[0].bytes;

    ret = aclrtMallocCached(&impl_->input_buffer, impl_->input_size, ACL_MEM_MALLOC_NORMAL_ONLY);
    if (ret != ACL_ERROR_NONE) {
        acl_failure("allocate", "aclrtMallocCached(input)", ret, model_path, 0, impl_->input_size, error);
        shutdown();
        return false;
    }
    ret = aclrtMallocCached(&impl_->output_buffer, impl_->output_size, ACL_MEM_MALLOC_NORMAL_ONLY);
    if (ret != ACL_ERROR_NONE) {
        acl_failure("allocate", "aclrtMallocCached(output)", ret, model_path, 0, impl_->output_size, error);
        shutdown();
        return false;
    }
    impl_->input_dataset = aclmdlCreateDataset();
    impl_->output_dataset = aclmdlCreateDataset();
    if (impl_->input_dataset == nullptr || impl_->output_dataset == nullptr) {
        if (error != nullptr) *error = "ACL error stage=dataset api=aclmdlCreateDataset ret=null model=" + model_path;
        shutdown();
        return false;
    }
    impl_->input_data_buffer = aclCreateDataBuffer(impl_->input_buffer, impl_->input_size);
    impl_->output_data_buffer = aclCreateDataBuffer(impl_->output_buffer, impl_->output_size);
    if (impl_->input_data_buffer == nullptr || impl_->output_data_buffer == nullptr) {
        if (error != nullptr) *error = "ACL error stage=dataset api=aclCreateDataBuffer ret=null model=" + model_path;
        shutdown();
        return false;
    }
    ret = aclmdlAddDatasetBuffer(impl_->input_dataset, impl_->input_data_buffer);
    if (ret != ACL_ERROR_NONE) {
        acl_failure("dataset", "aclmdlAddDatasetBuffer(input)", ret, model_path, 0, impl_->input_size, error);
        shutdown();
        return false;
    }
    ret = aclmdlAddDatasetBuffer(impl_->output_dataset, impl_->output_data_buffer);
    if (ret != ACL_ERROR_NONE) {
        acl_failure("dataset", "aclmdlAddDatasetBuffer(output)", ret, model_path, 0, impl_->output_size, error);
        shutdown();
        return false;
    }
    impl_->ready = true;
    if (error != nullptr) error->clear();
    return true;
}

bool Ss928AclDetector::infer(const unsigned char *nv12, std::size_t bytes,
                            AclInferenceResult *result, std::string *error) {
    if (!impl_->ready || nv12 == nullptr || result == nullptr) {
        if (error != nullptr) *error = "infer called with invalid state or argument";
        return false;
    }
    if (bytes != impl_->input_size) {
        std::ostringstream stream;
        stream << "input size mismatch: expected " << impl_->input_size << " bytes, got " << bytes;
        if (error != nullptr) *error = stream.str();
        return false;
    }
    std::memcpy(impl_->input_buffer, nv12, bytes);
    aclError ret = aclrtMemFlush(impl_->input_buffer, impl_->input_size);
    if (ret != ACL_ERROR_NONE) {
        return acl_failure("execute", "aclrtMemFlush(input)", ret, impl_->model_path, 0, impl_->input_size, error);
    }
    const auto begin = std::chrono::steady_clock::now();
    ret = aclmdlExecute(impl_->model_id, impl_->input_dataset, impl_->output_dataset);
    const auto end = std::chrono::steady_clock::now();
    if (ret != ACL_ERROR_NONE) {
        return acl_failure("execute", "aclmdlExecute", ret, impl_->model_path, 0, impl_->output_size, error);
    }
    ret = aclrtMemInvalidate(impl_->output_buffer, impl_->output_size);
    if (ret != ACL_ERROR_NONE) {
        return acl_failure("execute", "aclrtMemInvalidate(output)", ret, impl_->model_path, 0, impl_->output_size, error);
    }
    result->output = static_cast<const float *>(impl_->output_buffer);
    result->output_elements = impl_->output_size / sizeof(float);
    result->output_dims = impl_->output_info[0].dims;
    result->inference_ms = std::chrono::duration<double, std::milli>(end - begin).count();
    if (error != nullptr) error->clear();
    return true;
}

void Ss928AclDetector::shutdown() {
    if (impl_ == nullptr) return;
    impl_->ready = false;
    if (impl_->input_data_buffer != nullptr) {
        (void)aclDestroyDataBuffer(impl_->input_data_buffer);
        impl_->input_data_buffer = nullptr;
    }
    if (impl_->output_data_buffer != nullptr) {
        (void)aclDestroyDataBuffer(impl_->output_data_buffer);
        impl_->output_data_buffer = nullptr;
    }
    if (impl_->input_dataset != nullptr) {
        (void)aclmdlDestroyDataset(impl_->input_dataset);
        impl_->input_dataset = nullptr;
    }
    if (impl_->output_dataset != nullptr) {
        (void)aclmdlDestroyDataset(impl_->output_dataset);
        impl_->output_dataset = nullptr;
    }
    if (impl_->output_buffer != nullptr) {
        (void)aclrtFree(impl_->output_buffer);
        impl_->output_buffer = nullptr;
    }
    if (impl_->input_buffer != nullptr) {
        (void)aclrtFree(impl_->input_buffer);
        impl_->input_buffer = nullptr;
    }
    if (impl_->desc != nullptr) {
        (void)aclmdlDestroyDesc(impl_->desc);
        impl_->desc = nullptr;
    }
    if (impl_->model_loaded) {
        (void)aclmdlUnload(impl_->model_id);
        impl_->model_loaded = false;
    }
    if (impl_->model_weight != nullptr) {
        (void)aclrtFree(impl_->model_weight);
        impl_->model_weight = nullptr;
    }
    if (impl_->model_mem != nullptr) {
        (void)aclrtFree(impl_->model_mem);
        impl_->model_mem = nullptr;
    }
    if (impl_->device_set) {
        (void)aclrtResetDevice(impl_->device_id);
        impl_->device_set = false;
    }
    if (impl_->acl_initialized) {
        (void)aclFinalize();
        impl_->acl_initialized = false;
    }
    impl_->input_info.clear();
    impl_->output_info.clear();
    impl_->input_size = 0;
    impl_->output_size = 0;
}

bool Ss928AclDetector::initialized() const { return impl_->ready; }
std::size_t Ss928AclDetector::input_bytes() const { return impl_->input_size; }
const std::vector<ModelTensorInfo> &Ss928AclDetector::inputs() const { return impl_->input_info; }
const std::vector<ModelTensorInfo> &Ss928AclDetector::outputs() const { return impl_->output_info; }

#else

struct Ss928AclDetector::Impl {};
Ss928AclDetector::Ss928AclDetector() : impl_(new Impl) {}
Ss928AclDetector::~Ss928AclDetector() = default;
bool Ss928AclDetector::initialize(const std::string &, int, std::string *) { return false; }
bool Ss928AclDetector::infer(const unsigned char *, std::size_t, AclInferenceResult *, std::string *) { return false; }
void Ss928AclDetector::shutdown() {}
bool Ss928AclDetector::initialized() const { return false; }
std::size_t Ss928AclDetector::input_bytes() const { return 0; }
const std::vector<ModelTensorInfo> &Ss928AclDetector::inputs() const { static const std::vector<ModelTensorInfo> empty; return empty; }
const std::vector<ModelTensorInfo> &Ss928AclDetector::outputs() const { static const std::vector<ModelTensorInfo> empty; return empty; }

#endif
