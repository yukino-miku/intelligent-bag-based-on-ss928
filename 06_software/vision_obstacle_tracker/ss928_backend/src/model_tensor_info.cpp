#include "model_tensor_info.h"

#include <iomanip>
#include <sstream>

namespace {

std::string unknown_value(const char *prefix, int value) {
    std::ostringstream stream;
    stream << prefix << '(' << value << ')';
    return stream.str();
}

}  // namespace

std::string acl_dtype_name(int dtype) {
    switch (dtype) {
        case -1: return "UNDEFINED";
        case 0: return "FLOAT32";
        case 1: return "FLOAT16";
        case 2: return "INT8";
        case 3: return "INT32";
        case 4: return "UINT8";
        case 6: return "INT16";
        case 7: return "UINT16";
        case 8: return "UINT32";
        case 9: return "INT64";
        case 10: return "UINT64";
        case 11: return "DOUBLE";
        case 12: return "BOOL";
        case 13: return "STRING";
        case 16: return "COMPLEX64";
        case 17: return "COMPLEX128";
        default: return unknown_value("UNKNOWN", dtype);
    }
}

std::string acl_format_name(int format) {
    switch (format) {
        case -1: return "UNDEFINED";
        case 0: return "NCHW";
        case 1: return "NHWC";
        case 2: return "ND";
        case 3: return "NC1HWC0";
        case 4: return "FRACTAL_Z";
        case 12: return "NC1HWC0_C04";
        case 27: return "NDHWC";
        case 29: return "FRACTAL_NZ";
        case 30: return "NCDHW";
        case 32: return "NDC1HWC0";
        case 33: return "FRACTAL_Z_3D";
        default: return unknown_value("UNKNOWN", format);
    }
}

std::string json_escape(const std::string &value) {
    std::ostringstream stream;
    for (unsigned char ch : value) {
        switch (ch) {
            case '\"': stream << "\\\""; break;
            case '\\': stream << "\\\\"; break;
            case '\b': stream << "\\b"; break;
            case '\f': stream << "\\f"; break;
            case '\n': stream << "\\n"; break;
            case '\r': stream << "\\r"; break;
            case '\t': stream << "\\t"; break;
            default:
                if (ch < 0x20) {
                    stream << "\\u" << std::hex << std::setw(4) << std::setfill('0')
                           << static_cast<int>(ch) << std::dec;
                } else {
                    stream << static_cast<char>(ch);
                }
        }
    }
    return stream.str();
}

std::string dims_json(const std::vector<long long> &dims) {
    std::ostringstream stream;
    stream << '[';
    for (std::size_t i = 0; i < dims.size(); ++i) {
        if (i != 0) {
            stream << ',';
        }
        stream << dims[i];
    }
    stream << ']';
    return stream.str();
}

std::string tensor_json(const ModelTensorInfo &tensor, std::size_t index) {
    std::ostringstream stream;
    stream << "{\"index\":" << index
           << ",\"name\":\"" << json_escape(tensor.name) << '\"'
           << ",\"dtype\":\"" << acl_dtype_name(tensor.dtype) << '\"'
           << ",\"dtype_code\":" << tensor.dtype
           << ",\"format\":\"" << acl_format_name(tensor.format) << '\"'
           << ",\"format_code\":" << tensor.format
           << ",\"dims\":" << dims_json(tensor.dims)
           << ",\"bytes\":" << tensor.bytes << '}';
    return stream.str();
}
