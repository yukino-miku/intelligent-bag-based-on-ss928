#include "smartbag_ss928_acl.h"

#include <acl.h>

#include <algorithm>
#include <chrono>
#include <cstring>
#include <mutex>
#include <new>
#include <sstream>
#include <string>

namespace {

constexpr int kSuccess = 0;
constexpr int kInvalidArgument = -1;
constexpr int kAclFailure = -2;
constexpr int kModelContractFailure = -3;

struct Runtime {
    uint32_t model_id = 0;
    aclmdlDesc *model_desc = nullptr;
    aclmdlDataset *input_dataset = nullptr;
    aclmdlDataset *output_dataset = nullptr;
    aclDataBuffer *input_data_buffer = nullptr;
    aclDataBuffer *output_data_buffer = nullptr;
    void *input_buffer = nullptr;
    void *output_buffer = nullptr;
    size_t input_size = 0;
    size_t output_size = 0;
    smartbag_ss928_tensor_info input_info{};
    smartbag_ss928_tensor_info output_info{};
    bool acl_initialized = false;
    bool model_loaded = false;
    std::mutex inference_mutex;
};

void SetError(char *buffer, size_t size, const std::string &message)
{
    if (buffer == nullptr || size == 0) {
        return;
    }
    const size_t copy_size = std::min(size - 1, message.size());
    std::memcpy(buffer, message.data(), copy_size);
    buffer[copy_size] = '\0';
}

std::string AclError(const char *operation, aclError status)
{
    std::ostringstream stream;
    stream << operation << " failed with ACL status " << status;
    return stream.str();
}

void DestroyDataset(aclmdlDataset *dataset)
{
    if (dataset == nullptr) {
        return;
    }
    const size_t count = aclmdlGetDatasetNumBuffers(dataset);
    for (size_t index = 0; index < count; ++index) {
        aclDataBuffer *buffer = aclmdlGetDatasetBuffer(dataset, index);
        if (buffer != nullptr) {
            aclDestroyDataBuffer(buffer);
        }
    }
    aclmdlDestroyDataset(dataset);
}

void PopulateInfo(
    aclmdlDesc *description,
    bool input,
    smartbag_ss928_tensor_info *info)
{
    std::memset(info, 0, sizeof(*info));
    aclmdlIODims dimensions{};
    if (input) {
        info->data_type = static_cast<int32_t>(aclmdlGetInputDataType(description, 0));
        info->data_format = static_cast<int32_t>(aclmdlGetInputFormat(description, 0));
        info->byte_size = static_cast<uint64_t>(aclmdlGetInputSizeByIndex(description, 0));
        aclmdlGetInputDims(description, 0, &dimensions);
    } else {
        info->data_type = static_cast<int32_t>(aclmdlGetOutputDataType(description, 0));
        info->data_format = static_cast<int32_t>(aclmdlGetOutputFormat(description, 0));
        info->byte_size = static_cast<uint64_t>(aclmdlGetOutputSizeByIndex(description, 0));
        aclmdlGetOutputDims(description, 0, &dimensions);
    }
    info->dim_count = static_cast<uint32_t>(
        std::min<size_t>(dimensions.dimCount, SMARTBAG_SS928_MAX_DIMS));
    for (uint32_t index = 0; index < info->dim_count; ++index) {
        info->dims[index] = dimensions.dims[index];
    }
}

void Cleanup(Runtime *runtime)
{
    if (runtime == nullptr) {
        return;
    }
    if (runtime->model_loaded) {
        aclmdlUnload(runtime->model_id);
        runtime->model_loaded = false;
    }
    if (runtime->model_desc != nullptr) {
        aclmdlDestroyDesc(runtime->model_desc);
        runtime->model_desc = nullptr;
    }
    DestroyDataset(runtime->input_dataset);
    runtime->input_dataset = nullptr;
    runtime->input_data_buffer = nullptr;
    DestroyDataset(runtime->output_dataset);
    runtime->output_dataset = nullptr;
    runtime->output_data_buffer = nullptr;
    if (runtime->input_buffer != nullptr) {
        aclrtFree(runtime->input_buffer);
        runtime->input_buffer = nullptr;
    }
    if (runtime->output_buffer != nullptr) {
        aclrtFree(runtime->output_buffer);
        runtime->output_buffer = nullptr;
    }

    // The board ACL supplied with the current SS928 image crashes in
    // aclFinalize() after an otherwise clean model unload. This process owns
    // one runtime for its full lifetime, so OS process cleanup is the safer
    // boundary until the vendor runtime is updated.
}

int AllocateDataset(
    size_t size,
    void **device_buffer,
    aclDataBuffer **data_buffer,
    aclmdlDataset **dataset,
    std::string *error)
{
    aclError status = aclrtMalloc(device_buffer, size, ACL_MEM_MALLOC_NORMAL_ONLY);
    if (status != ACL_SUCCESS) {
        *error = AclError("aclrtMalloc", status);
        return kAclFailure;
    }
    *data_buffer = aclCreateDataBuffer(*device_buffer, size);
    if (*data_buffer == nullptr) {
        *error = "aclCreateDataBuffer returned null";
        aclrtFree(*device_buffer);
        *device_buffer = nullptr;
        return kAclFailure;
    }
    *dataset = aclmdlCreateDataset();
    if (*dataset == nullptr) {
        *error = "aclmdlCreateDataset returned null";
        aclDestroyDataBuffer(*data_buffer);
        *data_buffer = nullptr;
        aclrtFree(*device_buffer);
        *device_buffer = nullptr;
        return kAclFailure;
    }
    status = aclmdlAddDatasetBuffer(*dataset, *data_buffer);
    if (status != ACL_SUCCESS) {
        *error = AclError("aclmdlAddDatasetBuffer", status);
        aclmdlDestroyDataset(*dataset);
        *dataset = nullptr;
        aclDestroyDataBuffer(*data_buffer);
        *data_buffer = nullptr;
        aclrtFree(*device_buffer);
        *device_buffer = nullptr;
        return kAclFailure;
    }
    return kSuccess;
}

} // namespace

extern "C" int smartbag_ss928_create(
    const char *model_path,
    const char *acl_config_path,
    void **handle,
    char *error_message,
    size_t error_message_size)
{
    if (model_path == nullptr || handle == nullptr) {
        SetError(error_message, error_message_size, "model_path and handle are required");
        return kInvalidArgument;
    }
    *handle = nullptr;
    Runtime *runtime = new (std::nothrow) Runtime();
    if (runtime == nullptr) {
        SetError(error_message, error_message_size, "failed to allocate runtime");
        return kInvalidArgument;
    }
    std::string error;
    const char *config = (acl_config_path != nullptr && acl_config_path[0] != '\0')
        ? acl_config_path
        : nullptr;
    aclError status = aclInit(config);
    if (status != ACL_SUCCESS) {
        error = AclError("aclInit", status);
        Cleanup(runtime);
        delete runtime;
        SetError(error_message, error_message_size, error);
        return kAclFailure;
    }
    runtime->acl_initialized = true;
    status = aclrtSetDevice(0);
    if (status != ACL_SUCCESS) {
        error = AclError("aclrtSetDevice", status);
        Cleanup(runtime);
        delete runtime;
        SetError(error_message, error_message_size, error);
        return kAclFailure;
    }
    status = aclmdlLoadFromFile(model_path, &runtime->model_id);
    if (status != ACL_SUCCESS) {
        error = AclError("aclmdlLoadFromFile", status);
        Cleanup(runtime);
        delete runtime;
        SetError(error_message, error_message_size, error);
        return kAclFailure;
    }
    runtime->model_loaded = true;
    runtime->model_desc = aclmdlCreateDesc();
    if (runtime->model_desc == nullptr) {
        error = "aclmdlCreateDesc returned null";
        Cleanup(runtime);
        delete runtime;
        SetError(error_message, error_message_size, error);
        return kAclFailure;
    }
    status = aclmdlGetDesc(runtime->model_desc, runtime->model_id);
    if (status != ACL_SUCCESS) {
        error = AclError("aclmdlGetDesc", status);
        Cleanup(runtime);
        delete runtime;
        SetError(error_message, error_message_size, error);
        return kAclFailure;
    }
    if (aclmdlGetNumInputs(runtime->model_desc) != 1 ||
        aclmdlGetNumOutputs(runtime->model_desc) != 1) {
        error = "verified runtime requires exactly one model input and one output";
        Cleanup(runtime);
        delete runtime;
        SetError(error_message, error_message_size, error);
        return kModelContractFailure;
    }
    PopulateInfo(runtime->model_desc, true, &runtime->input_info);
    PopulateInfo(runtime->model_desc, false, &runtime->output_info);
    runtime->input_size = static_cast<size_t>(runtime->input_info.byte_size);
    runtime->output_size = static_cast<size_t>(runtime->output_info.byte_size);
    int result = AllocateDataset(
        runtime->input_size,
        &runtime->input_buffer,
        &runtime->input_data_buffer,
        &runtime->input_dataset,
        &error);
    if (result == kSuccess) {
        result = AllocateDataset(
            runtime->output_size,
            &runtime->output_buffer,
            &runtime->output_data_buffer,
            &runtime->output_dataset,
            &error);
    }
    if (result != kSuccess) {
        Cleanup(runtime);
        delete runtime;
        SetError(error_message, error_message_size, error);
        return result;
    }
    *handle = runtime;
    SetError(error_message, error_message_size, "");
    return kSuccess;
}

extern "C" int smartbag_ss928_get_input_info(
    void *handle,
    smartbag_ss928_tensor_info *info)
{
    if (handle == nullptr || info == nullptr) {
        return kInvalidArgument;
    }
    *info = static_cast<Runtime *>(handle)->input_info;
    return kSuccess;
}

extern "C" int smartbag_ss928_get_output_info(
    void *handle,
    smartbag_ss928_tensor_info *info)
{
    if (handle == nullptr || info == nullptr) {
        return kInvalidArgument;
    }
    *info = static_cast<Runtime *>(handle)->output_info;
    return kSuccess;
}

extern "C" int smartbag_ss928_infer(
    void *handle,
    const void *input,
    size_t input_size,
    void *output,
    size_t output_size,
    double *inference_ms,
    char *error_message,
    size_t error_message_size)
{
    if (handle == nullptr || input == nullptr || output == nullptr) {
        SetError(error_message, error_message_size, "handle, input and output are required");
        return kInvalidArgument;
    }
    Runtime *runtime = static_cast<Runtime *>(handle);
    if (input_size != runtime->input_size || output_size < runtime->output_size) {
        SetError(error_message, error_message_size, "input or output byte size does not match model");
        return kModelContractFailure;
    }
    std::lock_guard<std::mutex> lock(runtime->inference_mutex);
    std::memcpy(runtime->input_buffer, input, runtime->input_size);
    const auto started = std::chrono::steady_clock::now();
    const aclError status = aclmdlExecute(
        runtime->model_id,
        runtime->input_dataset,
        runtime->output_dataset);
    const auto finished = std::chrono::steady_clock::now();
    if (status != ACL_SUCCESS) {
        SetError(error_message, error_message_size, AclError("aclmdlExecute", status));
        return kAclFailure;
    }
    std::memcpy(output, runtime->output_buffer, runtime->output_size);
    if (inference_ms != nullptr) {
        *inference_ms = std::chrono::duration<double, std::milli>(finished - started).count();
    }
    SetError(error_message, error_message_size, "");
    return kSuccess;
}

extern "C" void smartbag_ss928_destroy(void *handle)
{
    Runtime *runtime = static_cast<Runtime *>(handle);
    Cleanup(runtime);
    delete runtime;
}
