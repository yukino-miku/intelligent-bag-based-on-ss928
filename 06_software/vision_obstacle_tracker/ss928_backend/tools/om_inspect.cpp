#include "acl.h"
#include "model_tensor_info.h"

#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace {

struct InspectionResult {
    std::string model_path;
    std::size_t model_mem_size = 0;
    std::size_t model_weight_size = 0;
    int query_ret = -1;
    int load_ret = -1;
    int desc_ret = -1;
    int unload_ret = -1;
    int run_mode = -1;
    std::vector<ModelTensorInfo> inputs;
    std::vector<ModelTensorInfo> outputs;
    std::vector<int> input_aipp_types;
    std::vector<int> input_aipp_ret;
    std::vector<aclAippInfo> input_aipp_info;
    std::vector<int> input_aipp_info_ret;
};

const char *recent_acl_error() {
    const char *message = aclGetRecentErrMsg();
    return message == nullptr ? "" : message;
}

bool check_acl(const char *stage, const char *api, aclError ret, const std::string &model_path) {
    if (ret == ACL_ERROR_NONE) {
        return true;
    }
    std::cerr << "ACL error stage=" << stage << " api=" << api << " ret=" << ret
              << " model=" << model_path << " detail=" << recent_acl_error() << '\n';
    return false;
}

std::vector<long long> copy_dims(const aclmdlIODims &dims) {
    std::vector<long long> result;
    result.reserve(dims.dimCount);
    for (std::size_t i = 0; i < dims.dimCount; ++i) {
        result.push_back(static_cast<long long>(dims.dims[i]));
    }
    return result;
}

std::string aipp_type_name(int type) {
    switch (type) {
        case ACL_DATA_WITHOUT_AIPP: return "WITHOUT_AIPP";
        case ACL_DATA_WITH_STATIC_AIPP: return "STATIC_AIPP";
        case ACL_DATA_WITH_DYNAMIC_AIPP: return "DYNAMIC_AIPP";
        case ACL_DYNAMIC_AIPP_NODE: return "DYNAMIC_AIPP_NODE";
        default: {
            std::ostringstream stream;
            stream << "UNKNOWN(" << type << ')';
            return stream.str();
        }
    }
}

std::string aipp_input_format_name(int format) {
    switch (format) {
        case ACL_YUV420SP_U8: return "YUV420SP_U8";
        case ACL_XRGB8888_U8: return "XRGB8888_U8";
        case ACL_RGB888_U8: return "RGB888_U8";
        case ACL_YUV400_U8: return "YUV400_U8";
        case ACL_NC1HWC0DI_FP16: return "NC1HWC0DI_FP16";
        case ACL_NC1HWC0DI_S8: return "NC1HWC0DI_S8";
        case ACL_ARGB8888_U8: return "ARGB8888_U8";
        case ACL_YUYV_U8: return "YUYV_U8";
        case ACL_YUV422SP_U8: return "YUV422SP_U8";
        case ACL_AYUV444_U8: return "AYUV444_U8";
        case ACL_RAW10: return "RAW10";
        case ACL_RAW12: return "RAW12";
        case ACL_RAW16: return "RAW16";
        case ACL_RAW24: return "RAW24";
        default: return "UNKNOWN";
    }
}

std::string inspection_json(const InspectionResult &result) {
    std::ostringstream stream;
    stream << "{\n"
           << "  \"model_path\":\"" << json_escape(result.model_path) << "\",\n"
           << "  \"model_mem_size\":" << result.model_mem_size << ",\n"
           << "  \"model_weight_size\":" << result.model_weight_size << ",\n"
           << "  \"query_ret\":" << result.query_ret << ",\n"
           << "  \"load_ret\":" << result.load_ret << ",\n"
           << "  \"desc_ret\":" << result.desc_ret << ",\n"
           << "  \"unload_ret\":" << result.unload_ret << ",\n"
           << "  \"run_mode\":" << result.run_mode << ",\n"
           << "  \"inputs\":[";
    for (std::size_t i = 0; i < result.inputs.size(); ++i) {
        if (i != 0) stream << ',';
        stream << "\n    " << tensor_json(result.inputs[i], i);
    }
    if (!result.inputs.empty()) stream << '\n';
    stream << "  ],\n  \"input_aipp\":[";
    for (std::size_t i = 0; i < result.inputs.size(); ++i) {
        if (i != 0) stream << ',';
        stream << "\n    {\"index\":" << i
               << ",\"query_ret\":" << result.input_aipp_ret[i]
               << ",\"type\":\"" << aipp_type_name(result.input_aipp_types[i]) << "\""
               << ",\"type_code\":" << result.input_aipp_types[i]
               << ",\"info_ret\":" << result.input_aipp_info_ret[i];
        if (result.input_aipp_info_ret[i] == ACL_ERROR_NONE) {
            const aclAippInfo &info = result.input_aipp_info[i];
            stream << ",\"input_format\":\"" << aipp_input_format_name(info.inputFormat) << "\""
                   << ",\"input_format_code\":" << static_cast<int>(info.inputFormat)
                   << ",\"src_width\":" << info.srcImageSizeW
                   << ",\"src_height\":" << info.srcImageSizeH
                   << ",\"crop_switch\":" << static_cast<int>(info.cropSwitch)
                   << ",\"load_start_pos_w\":" << info.loadStartPosW
                   << ",\"load_start_pos_h\":" << info.loadStartPosH
                   << ",\"crop_size_w\":" << info.cropSizeW
                   << ",\"crop_size_h\":" << info.cropSizeH
                   << ",\"resize_switch\":" << static_cast<int>(info.resizeSwitch)
                   << ",\"resize_output_w\":" << info.resizeOutputW
                   << ",\"resize_output_h\":" << info.resizeOutputH
                   << ",\"padding_switch\":" << static_cast<int>(info.paddingSwitch)
                   << ",\"left_padding_size\":" << info.leftPaddingSize
                   << ",\"right_padding_size\":" << info.rightPaddingSize
                   << ",\"top_padding_size\":" << info.topPaddingSize
                   << ",\"bottom_padding_size\":" << info.bottomPaddingSize
                   << ",\"csc_switch\":" << static_cast<int>(info.cscSwitch)
                   << ",\"rbuv_swap_switch\":" << static_cast<int>(info.rbuvSwapSwitch)
                   << ",\"ax_swap_switch\":" << static_cast<int>(info.axSwapSwitch)
                   << ",\"single_line_mode\":" << static_cast<int>(info.singleLineMode)
                   << ",\"csc_matrix\":[" << info.matrixR0C0 << ',' << info.matrixR0C1 << ',' << info.matrixR0C2
                   << ',' << info.matrixR1C0 << ',' << info.matrixR1C1 << ',' << info.matrixR1C2
                   << ',' << info.matrixR2C0 << ',' << info.matrixR2C1 << ',' << info.matrixR2C2 << ']'
                   << ",\"input_bias\":[" << info.inputBias0 << ',' << info.inputBias1 << ',' << info.inputBias2 << ']'
                   << ",\"output_bias\":[" << info.outputBias0 << ',' << info.outputBias1 << ',' << info.outputBias2 << ']'
                   << ",\"mean\":[" << info.meanChn0 << ',' << info.meanChn1 << ',' << info.meanChn2 << ',' << info.meanChn3 << ']'
                   << ",\"min\":[" << info.minChn0 << ',' << info.minChn1 << ',' << info.minChn2 << ',' << info.minChn3 << ']'
                   << ",\"var_reci\":[" << info.varReciChn0 << ',' << info.varReciChn1 << ',' << info.varReciChn2 << ',' << info.varReciChn3 << ']'
                   << ",\"src_format\":\"" << acl_format_name(static_cast<int>(info.srcFormat)) << "\""
                   << ",\"src_format_code\":" << static_cast<int>(info.srcFormat)
                   << ",\"src_dtype\":\"" << acl_dtype_name(static_cast<int>(info.srcDatatype)) << "\""
                   << ",\"src_dtype_code\":" << static_cast<int>(info.srcDatatype)
                   << ",\"src_dim_num\":" << info.srcDimNum
                   << ",\"shape_count\":" << info.shapeCount
                   << ",\"aipp_extend_is_null\":" << (info.aippExtend == nullptr ? "true" : "false")
                   << ",\"out_dims\":[";
            for (std::size_t shape = 0; shape < info.shapeCount; ++shape) {
                if (shape != 0) stream << ',';
                stream << "{\"src_dims\":" << dims_json(copy_dims(info.outDims[shape].srcDims))
                       << ",\"src_size\":" << info.outDims[shape].srcSize
                       << ",\"aipp_out_dims\":" << dims_json(copy_dims(info.outDims[shape].aippOutdims))
                       << ",\"aipp_out_size\":" << info.outDims[shape].aippOutSize << '}';
            }
            stream << ']';
        }
        stream << '}';
    }
    if (!result.inputs.empty()) stream << '\n';
    stream << "  ],\n  \"outputs\":[";
    for (std::size_t i = 0; i < result.outputs.size(); ++i) {
        if (i != 0) stream << ',';
        stream << "\n    " << tensor_json(result.outputs[i], i);
    }
    if (!result.outputs.empty()) stream << '\n';
    stream << "  ]\n}\n";
    return stream.str();
}

void print_tensor(const char *kind, std::size_t index, const ModelTensorInfo &tensor) {
    std::cout << kind << '[' << index << "] name=" << tensor.name
              << " dtype=" << acl_dtype_name(tensor.dtype) << '(' << tensor.dtype << ')'
              << " format=" << acl_format_name(tensor.format) << '(' << tensor.format << ')'
              << " dims=" << dims_json(tensor.dims)
              << " bytes=" << tensor.bytes << '\n';
}

}  // namespace

int main(int argc, char **argv) {
    if (argc != 2 && argc != 4) {
        std::cerr << "Usage: " << argv[0] << " MODEL [--json PATH]\n";
        return 2;
    }
    if (argc == 4 && std::string(argv[2]) != "--json") {
        std::cerr << "expected --json before output path\n";
        return 2;
    }

    InspectionResult result;
    result.model_path = argv[1];
    const std::string json_path = argc == 4 ? argv[3] : "logs/model_desc.json";
    void *model_mem = nullptr;
    void *model_weight = nullptr;
    std::uint32_t model_id = 0;
    aclmdlDesc *desc = nullptr;
    bool acl_initialized = false;
    bool device_set = false;
    bool model_loaded = false;
    int exit_code = 1;

    aclError ret = aclInit("");
    if (!check_acl("init", "aclInit", ret, result.model_path)) goto cleanup;
    acl_initialized = true;

    ret = aclrtSetDevice(0);
    if (!check_acl("init", "aclrtSetDevice", ret, result.model_path)) goto cleanup;
    device_set = true;

    {
        aclrtRunMode run_mode = ACL_HOST;
        ret = aclrtGetRunMode(&run_mode);
        if (!check_acl("init", "aclrtGetRunMode", ret, result.model_path)) goto cleanup;
        result.run_mode = static_cast<int>(run_mode);
        std::cout << "aclrtRunMode=" << result.run_mode << '\n';
    }

    result.query_ret = aclmdlQuerySize(result.model_path.c_str(), &result.model_mem_size, &result.model_weight_size);
    std::cout << "aclmdlQuerySize ret=" << result.query_ret << " model_mem_size=" << result.model_mem_size
              << " model_weight_size=" << result.model_weight_size << '\n';
    if (!check_acl("query", "aclmdlQuerySize", result.query_ret, result.model_path)) goto cleanup;

    ret = aclrtMalloc(&model_mem, result.model_mem_size, ACL_MEM_MALLOC_HUGE_FIRST);
    if (!check_acl("allocate", "aclrtMalloc(model_mem)", ret, result.model_path)) goto cleanup;
    ret = aclrtMalloc(&model_weight, result.model_weight_size, ACL_MEM_MALLOC_HUGE_FIRST);
    if (!check_acl("allocate", "aclrtMalloc(model_weight)", ret, result.model_path)) goto cleanup;

    result.load_ret = aclmdlLoadFromFileWithMem(
        result.model_path.c_str(), &model_id,
        model_mem, result.model_mem_size, model_weight, result.model_weight_size);
    std::cout << "aclmdlLoadFromFileWithMem ret=" << result.load_ret << " model_id=" << model_id << '\n';
    if (!check_acl("load", "aclmdlLoadFromFileWithMem", result.load_ret, result.model_path)) goto cleanup;
    model_loaded = true;

    desc = aclmdlCreateDesc();
    if (desc == nullptr) {
        std::cerr << "ACL error stage=descriptor api=aclmdlCreateDesc ret=null model=" << result.model_path << '\n';
        goto cleanup;
    }
    result.desc_ret = aclmdlGetDesc(desc, model_id);
    std::cout << "aclmdlGetDesc ret=" << result.desc_ret << '\n';
    if (!check_acl("descriptor", "aclmdlGetDesc", result.desc_ret, result.model_path)) goto cleanup;

    {
        const std::size_t count = aclmdlGetNumInputs(desc);
        result.inputs.reserve(count);
        result.input_aipp_types.reserve(count);
        result.input_aipp_ret.reserve(count);
        result.input_aipp_info.resize(count);
        result.input_aipp_info_ret.reserve(count);
        std::cout << "input_count=" << count << '\n';
        for (std::size_t i = 0; i < count; ++i) {
            aclmdlIODims dims{};
            ret = aclmdlGetInputDimsV2(desc, i, &dims);
            if (!check_acl("descriptor", "aclmdlGetInputDimsV2", ret, result.model_path)) goto cleanup;
            ModelTensorInfo tensor;
            const char *name = aclmdlGetInputNameByIndex(desc, i);
            tensor.name = name == nullptr || *name == '\0' ? dims.name : name;
            tensor.dtype = static_cast<int>(aclmdlGetInputDataType(desc, i));
            tensor.format = static_cast<int>(aclmdlGetInputFormat(desc, i));
            tensor.dims = copy_dims(dims);
            tensor.bytes = aclmdlGetInputSizeByIndex(desc, i);
            result.inputs.push_back(tensor);
            print_tensor("input", i, tensor);

            aclmdlInputAippType aipp_type = ACL_DATA_WITHOUT_AIPP;
            std::size_t dynamic_index = 0;
            const int aipp_ret = aclmdlGetAippType(model_id, i, &aipp_type, &dynamic_index);
            result.input_aipp_ret.push_back(aipp_ret);
            result.input_aipp_types.push_back(static_cast<int>(aipp_type));
            std::memset(&result.input_aipp_info[i], 0, sizeof(aclAippInfo));
            const int info_ret = aclmdlGetFirstAippInfo(model_id, i, &result.input_aipp_info[i]);
            result.input_aipp_info_ret.push_back(info_ret);
            std::cout << "input_aipp[" << i << "] query_ret=" << aipp_ret
                      << " type=" << aipp_type_name(aipp_type) << '(' << static_cast<int>(aipp_type) << ')'
                      << " dynamic_index=" << dynamic_index << " info_ret=" << info_ret;
            if (info_ret == ACL_ERROR_NONE) {
                const aclAippInfo &info = result.input_aipp_info[i];
                std::cout << " input_format=" << aipp_input_format_name(info.inputFormat)
                          << '(' << static_cast<int>(info.inputFormat) << ')'
                          << " src=" << info.srcImageSizeW << 'x' << info.srcImageSizeH
                          << " crop=" << static_cast<int>(info.cropSwitch)
                          << " crop_origin=" << info.loadStartPosW << ',' << info.loadStartPosH
                          << " crop_size=" << info.cropSizeW << 'x' << info.cropSizeH
                          << " resize=" << static_cast<int>(info.resizeSwitch)
                          << " resize_output=" << info.resizeOutputW << 'x' << info.resizeOutputH
                          << " padding=" << static_cast<int>(info.paddingSwitch)
                          << " padding_lrtb=" << info.leftPaddingSize << ',' << info.rightPaddingSize
                          << ',' << info.topPaddingSize << ',' << info.bottomPaddingSize
                          << " csc=" << static_cast<int>(info.cscSwitch)
                          << " rbuv_swap=" << static_cast<int>(info.rbuvSwapSwitch)
                          << " ax_swap=" << static_cast<int>(info.axSwapSwitch)
                          << " single_line=" << static_cast<int>(info.singleLineMode)
                          << " csc_matrix=" << info.matrixR0C0 << ',' << info.matrixR0C1 << ',' << info.matrixR0C2
                          << ',' << info.matrixR1C0 << ',' << info.matrixR1C1 << ',' << info.matrixR1C2
                          << ',' << info.matrixR2C0 << ',' << info.matrixR2C1 << ',' << info.matrixR2C2
                          << " input_bias=" << info.inputBias0 << ',' << info.inputBias1 << ',' << info.inputBias2
                          << " output_bias=" << info.outputBias0 << ',' << info.outputBias1 << ',' << info.outputBias2
                          << " mean=" << info.meanChn0 << ',' << info.meanChn1 << ',' << info.meanChn2 << ',' << info.meanChn3
                          << " min=" << info.minChn0 << ',' << info.minChn1 << ',' << info.minChn2 << ',' << info.minChn3
                          << " var_reci=" << info.varReciChn0 << ',' << info.varReciChn1 << ',' << info.varReciChn2 << ',' << info.varReciChn3
                          << " src_format=" << acl_format_name(static_cast<int>(info.srcFormat))
                          << '(' << static_cast<int>(info.srcFormat) << ')'
                          << " src_dtype=" << acl_dtype_name(static_cast<int>(info.srcDatatype))
                          << '(' << static_cast<int>(info.srcDatatype) << ')'
                          << " src_dim_num=" << info.srcDimNum
                          << " shape_count=" << info.shapeCount
                          << " aipp_extend_is_null=" << (info.aippExtend == nullptr ? 1 : 0);
                for (std::size_t shape = 0; shape < info.shapeCount; ++shape) {
                    std::cout << " shape[" << shape << "].src_dims="
                              << dims_json(copy_dims(info.outDims[shape].srcDims))
                              << " shape[" << shape << "].src_size=" << info.outDims[shape].srcSize
                              << " shape[" << shape << "].aipp_out_dims="
                              << dims_json(copy_dims(info.outDims[shape].aippOutdims))
                              << " shape[" << shape << "].aipp_out_size=" << info.outDims[shape].aippOutSize;
                }
            }
            std::cout << '\n';
        }
    }

    {
        const std::size_t count = aclmdlGetNumOutputs(desc);
        result.outputs.reserve(count);
        std::cout << "output_count=" << count << '\n';
        for (std::size_t i = 0; i < count; ++i) {
            aclmdlIODims dims{};
            ret = aclmdlGetOutputDims(desc, i, &dims);
            if (!check_acl("descriptor", "aclmdlGetOutputDims", ret, result.model_path)) goto cleanup;
            ModelTensorInfo tensor;
            const char *name = aclmdlGetOutputNameByIndex(desc, i);
            tensor.name = name == nullptr || *name == '\0' ? dims.name : name;
            tensor.dtype = static_cast<int>(aclmdlGetOutputDataType(desc, i));
            tensor.format = static_cast<int>(aclmdlGetOutputFormat(desc, i));
            tensor.dims = copy_dims(dims);
            tensor.bytes = aclmdlGetOutputSizeByIndex(desc, i);
            result.outputs.push_back(tensor);
            print_tensor("output", i, tensor);
        }
    }
    exit_code = 0;

cleanup:
    if (desc != nullptr) {
        const aclError destroy_ret = aclmdlDestroyDesc(desc);
        std::cout << "aclmdlDestroyDesc ret=" << destroy_ret << '\n';
        desc = nullptr;
        if (destroy_ret != ACL_ERROR_NONE) exit_code = 1;
    }
    if (model_loaded) {
        result.unload_ret = aclmdlUnload(model_id);
        std::cout << "aclmdlUnload ret=" << result.unload_ret << " model_id=" << model_id << '\n';
        if (result.unload_ret != ACL_ERROR_NONE) exit_code = 1;
    }
    if (model_weight != nullptr) {
        ret = aclrtFree(model_weight);
        std::cout << "aclrtFree(model_weight) ret=" << ret << '\n';
        if (ret != ACL_ERROR_NONE) exit_code = 1;
    }
    if (model_mem != nullptr) {
        ret = aclrtFree(model_mem);
        std::cout << "aclrtFree(model_mem) ret=" << ret << '\n';
        if (ret != ACL_ERROR_NONE) exit_code = 1;
    }
    if (device_set) {
        ret = aclrtResetDevice(0);
        std::cout << "aclrtResetDevice ret=" << ret << '\n';
        if (ret != ACL_ERROR_NONE) exit_code = 1;
    }
    if (acl_initialized) {
        ret = aclFinalize();
        std::cout << "aclFinalize ret=" << ret << '\n';
        if (ret != ACL_ERROR_NONE) exit_code = 1;
    }

    if (!result.inputs.empty() || !result.outputs.empty()) {
        std::ofstream json_file(json_path, std::ios::binary | std::ios::trunc);
        if (!json_file) {
            std::cerr << "could not open JSON output: " << json_path << '\n';
            return 1;
        }
        json_file << inspection_json(result);
        if (!json_file) {
            std::cerr << "could not write JSON output: " << json_path << '\n';
            return 1;
        }
        std::cout << "model_desc_json=" << json_path << '\n';
    }
    return exit_code;
}
