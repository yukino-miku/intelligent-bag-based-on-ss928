#ifndef FRAME_PREPROCESS_H
#define FRAME_PREPROCESS_H

#include <cstddef>
#include <string>
#include <vector>

struct LetterboxInfo {
    int source_width = 0;
    int source_height = 0;
    int model_width = 0;
    int model_height = 0;
    int resized_width = 0;
    int resized_height = 0;
    float scale = 0.0f;
    float pad_x = 0.0f;
    float pad_y = 0.0f;
};

bool compute_letterbox(
    int source_width,
    int source_height,
    int model_width,
    int model_height,
    LetterboxInfo *info,
    std::string *error);

void restore_box_to_source(
    const LetterboxInfo &info,
    double *x1,
    double *y1,
    double *x2,
    double *y2);

bool bgr_letterbox_to_nv12(
    const unsigned char *source_bgr,
    std::size_t source_bytes,
    int source_width,
    int source_height,
    int source_stride,
    int model_width,
    int model_height,
    std::vector<unsigned char> *nv12,
    std::vector<unsigned char> *letterbox_bgr,
    LetterboxInfo *info,
    std::string *error);

#endif
