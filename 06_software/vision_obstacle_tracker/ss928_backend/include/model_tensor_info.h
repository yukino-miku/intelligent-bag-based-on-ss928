#ifndef MODEL_TENSOR_INFO_H
#define MODEL_TENSOR_INFO_H

#include <cstddef>
#include <string>
#include <vector>

struct ModelTensorInfo {
    std::string name;
    int dtype = -1;
    int format = -1;
    std::vector<long long> dims;
    std::size_t bytes = 0;
};

std::string acl_dtype_name(int dtype);
std::string acl_format_name(int format);
std::string json_escape(const std::string &value);
std::string dims_json(const std::vector<long long> &dims);
std::string tensor_json(const ModelTensorInfo &tensor, std::size_t index);

#endif
