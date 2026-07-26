#include "acl.h"

#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

// Reference path intentionally follows the V2.0.2.2 official implementation:
// sample_npu_process.c allocates input with aclrtMalloc and fread()s bytes
// directly into it; sample_npu_model.c binds the buffer, allocates every output
// with aclrtMalloc, calls aclmdlExecute, and reads output dataset buffers.

namespace {

const char *detail() {
    const char *message = aclGetRecentErrMsg();
    return message == nullptr ? "" : message;
}

bool ok(const char *api, aclError ret) {
    if (ret == ACL_ERROR_NONE) return true;
    std::cerr << "ACL error api=" << api << " ret=" << ret << " detail=" << detail() << '\n';
    return false;
}

bool file_size(const std::string &path, std::size_t *size) {
    std::ifstream input(path, std::ios::binary | std::ios::ate);
    if (!input) return false;
    const std::streamoff value = input.tellg();
    if (value < 0) return false;
    *size = static_cast<std::size_t>(value);
    return true;
}

bool fread_direct(const std::string &path, void *destination, std::size_t bytes) {
    FILE *input = std::fopen(path.c_str(), "rb");
    if (input == nullptr) return false;
    const std::size_t count = std::fread(destination, bytes, 1, input);
    const int extra = std::fgetc(input);
    std::fclose(input);
    return count == 1 && extra == EOF;
}

bool write_all(const std::string &path, const void *data, std::size_t bytes) {
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    output.write(static_cast<const char *>(data), static_cast<std::streamsize>(bytes));
    return static_cast<bool>(output);
}

std::string dims_string(const aclmdlIODims &dims) {
    std::string value;
    for (std::size_t i = 0; i < dims.dimCount; ++i) {
        if (i != 0) value += ',';
        value += std::to_string(dims.dims[i]);
    }
    return value;
}

}  // namespace

int main(int argc, char **argv) {
    if (argc != 4) {
        std::cerr << "Usage: " << argv[0] << " MODEL INPUT_RAW OUTPUT_PREFIX\n";
        return 2;
    }
    const std::string model_path = argv[1];
    const std::string input_path = argv[2];
    const std::string output_prefix = argv[3];

    bool acl_initialized = false;
    bool device_set = false;
    bool model_loaded = false;
    std::uint32_t model_id = 0;
    void *model_mem = nullptr;
    void *model_weight = nullptr;
    std::size_t model_mem_size = 0;
    std::size_t model_weight_size = 0;
    aclmdlDesc *desc = nullptr;
    aclmdlDataset *input_dataset = nullptr;
    aclmdlDataset *output_dataset = nullptr;
    aclDataBuffer *input_data = nullptr;
    std::vector<aclDataBuffer *> output_data;
    void *input_buffer = nullptr;
    std::vector<void *> output_buffers;
    int exit_code = 1;

    aclError ret = aclInit("");
    if (!ok("aclInit", ret)) goto cleanup;
    acl_initialized = true;
    ret = aclrtSetDevice(0);
    if (!ok("aclrtSetDevice", ret)) goto cleanup;
    device_set = true;

    ret = aclmdlQuerySize(model_path.c_str(), &model_mem_size, &model_weight_size);
    if (!ok("aclmdlQuerySize", ret)) goto cleanup;
    ret = aclrtMalloc(&model_mem, model_mem_size, ACL_MEM_MALLOC_HUGE_FIRST);
    if (!ok("aclrtMalloc(model_mem)", ret)) goto cleanup;
    ret = aclrtMalloc(&model_weight, model_weight_size, ACL_MEM_MALLOC_HUGE_FIRST);
    if (!ok("aclrtMalloc(model_weight)", ret)) goto cleanup;
    ret = aclmdlLoadFromFileWithMem(model_path.c_str(), &model_id,
        model_mem, model_mem_size, model_weight, model_weight_size);
    if (!ok("aclmdlLoadFromFileWithMem", ret)) goto cleanup;
    model_loaded = true;

    desc = aclmdlCreateDesc();
    if (desc == nullptr) {
        std::cerr << "aclmdlCreateDesc returned null\n";
        goto cleanup;
    }
    ret = aclmdlGetDesc(desc, model_id);
    if (!ok("aclmdlGetDesc", ret)) goto cleanup;

    {
        const std::size_t input_count = aclmdlGetNumInputs(desc);
        const std::size_t output_count = aclmdlGetNumOutputs(desc);
        if (input_count != 1 || output_count == 0) {
            std::cerr << "unexpected tensor counts input=" << input_count
                      << " output=" << output_count << '\n';
            goto cleanup;
        }
        const std::size_t expected_input_bytes = aclmdlGetInputSizeByIndex(desc, 0);
        std::size_t actual_input_bytes = 0;
        if (!file_size(input_path, &actual_input_bytes) || actual_input_bytes != expected_input_bytes) {
            std::cerr << "input size mismatch expected=" << expected_input_bytes
                      << " actual=" << actual_input_bytes << '\n';
            goto cleanup;
        }

        ret = aclrtMalloc(&input_buffer, expected_input_bytes, ACL_MEM_MALLOC_NORMAL_ONLY);
        if (!ok("aclrtMalloc(input)", ret)) goto cleanup;
        if (!fread_direct(input_path, input_buffer, expected_input_bytes)) {
            std::cerr << "fread directly into ACL input failed: " << input_path << '\n';
            goto cleanup;
        }
        input_dataset = aclmdlCreateDataset();
        if (input_dataset == nullptr) {
            std::cerr << "aclmdlCreateDataset(input) returned null\n";
            goto cleanup;
        }
        input_data = aclCreateDataBuffer(input_buffer, expected_input_bytes);
        if (input_data == nullptr) {
            std::cerr << "aclCreateDataBuffer(input) returned null\n";
            goto cleanup;
        }
        ret = aclmdlAddDatasetBuffer(input_dataset, input_data);
        if (!ok("aclmdlAddDatasetBuffer(input)", ret)) goto cleanup;

        output_dataset = aclmdlCreateDataset();
        if (output_dataset == nullptr) {
            std::cerr << "aclmdlCreateDataset(output) returned null\n";
            goto cleanup;
        }
        output_buffers.resize(output_count, nullptr);
        output_data.resize(output_count, nullptr);
        for (std::size_t i = 0; i < output_count; ++i) {
            const std::size_t bytes = aclmdlGetOutputSizeByIndex(desc, i);
            ret = aclrtMalloc(&output_buffers[i], bytes, ACL_MEM_MALLOC_NORMAL_ONLY);
            if (!ok("aclrtMalloc(output)", ret)) goto cleanup;
            output_data[i] = aclCreateDataBuffer(output_buffers[i], bytes);
            if (output_data[i] == nullptr) {
                std::cerr << "aclCreateDataBuffer(output) returned null index=" << i << '\n';
                goto cleanup;
            }
            ret = aclmdlAddDatasetBuffer(output_dataset, output_data[i]);
            if (!ok("aclmdlAddDatasetBuffer(output)", ret)) goto cleanup;
        }

        ret = aclmdlExecute(model_id, input_dataset, output_dataset);
        if (!ok("aclmdlExecute", ret)) goto cleanup;

        std::cout << "runner=official_sdk_reference input_path=" << input_path
                  << " input_bytes=" << expected_input_bytes
                  << " output_count=" << output_count;
        for (std::size_t i = 0; i < output_count; ++i) {
            aclDataBuffer *buffer = aclmdlGetDatasetBuffer(output_dataset, i);
            if (buffer == nullptr) {
                std::cerr << "aclmdlGetDatasetBuffer returned null index=" << i << '\n';
                goto cleanup;
            }
            const void *address = aclGetDataBufferAddr(buffer);
            const std::size_t bytes = aclGetDataBufferSizeV2(buffer);
            aclmdlIODims dims{};
            ret = aclmdlGetOutputDims(desc, i, &dims);
            if (!ok("aclmdlGetOutputDims", ret)) goto cleanup;
            const std::string path = output_prefix + ".output" + std::to_string(i) + ".bin";
            if (address == nullptr || !write_all(path, address, bytes)) {
                std::cerr << "could not write output index=" << i << " path=" << path << '\n';
                goto cleanup;
            }
            std::cout << " output[" << i << "].path=" << path
                      << " output[" << i << "].bytes=" << bytes
                      << " output[" << i << "].dims=" << dims_string(dims);
        }
        std::cout << '\n';
    }
    exit_code = 0;

cleanup:
    if (input_data != nullptr) (void)aclDestroyDataBuffer(input_data);
    for (aclDataBuffer *buffer : output_data) {
        if (buffer != nullptr) (void)aclDestroyDataBuffer(buffer);
    }
    if (input_dataset != nullptr) (void)aclmdlDestroyDataset(input_dataset);
    if (output_dataset != nullptr) (void)aclmdlDestroyDataset(output_dataset);
    if (input_buffer != nullptr) (void)aclrtFree(input_buffer);
    for (void *buffer : output_buffers) {
        if (buffer != nullptr) (void)aclrtFree(buffer);
    }
    if (desc != nullptr) (void)aclmdlDestroyDesc(desc);
    if (model_loaded) (void)aclmdlUnload(model_id);
    if (model_weight != nullptr) (void)aclrtFree(model_weight);
    if (model_mem != nullptr) (void)aclrtFree(model_mem);
    if (device_set) (void)aclrtResetDevice(0);
    if (acl_initialized) (void)aclFinalize();
    return exit_code;
}
