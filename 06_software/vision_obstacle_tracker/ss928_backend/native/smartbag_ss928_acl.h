#pragma once

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define SMARTBAG_SS928_MAX_DIMS 8

typedef struct smartbag_ss928_tensor_info {
    int32_t data_type;
    int32_t data_format;
    uint32_t dim_count;
    int64_t dims[SMARTBAG_SS928_MAX_DIMS];
    uint64_t byte_size;
} smartbag_ss928_tensor_info;

int smartbag_ss928_create(
    const char *model_path,
    const char *acl_config_path,
    void **handle,
    char *error_message,
    size_t error_message_size);

int smartbag_ss928_get_input_info(void *handle, smartbag_ss928_tensor_info *info);
int smartbag_ss928_get_output_info(void *handle, smartbag_ss928_tensor_info *info);

int smartbag_ss928_infer(
    void *handle,
    const void *input,
    size_t input_size,
    void *output,
    size_t output_size,
    double *inference_ms,
    char *error_message,
    size_t error_message_size);

void smartbag_ss928_destroy(void *handle);

#ifdef __cplusplus
}
#endif
