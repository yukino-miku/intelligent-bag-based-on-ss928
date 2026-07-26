#include "frame_preprocess.h"

#include <algorithm>
#include <cmath>

namespace {

int clamp_int(int value, int low, int high) {
    return std::max(low, std::min(high, value));
}

double clamp_double(double value, double low, double high) {
    return std::max(low, std::min(high, value));
}

unsigned char clamp_u8(int value) {
    return static_cast<unsigned char>(clamp_int(value, 0, 255));
}

void sample_bilinear_bgr(
    const unsigned char *source,
    int width,
    int height,
    int stride,
    double source_x,
    double source_y,
    unsigned char *out) {
    const double x = clamp_double(source_x, 0.0, static_cast<double>(width - 1));
    const double y = clamp_double(source_y, 0.0, static_cast<double>(height - 1));
    const int x0 = static_cast<int>(std::floor(x));
    const int y0 = static_cast<int>(std::floor(y));
    const int x1 = std::min(x0 + 1, width - 1);
    const int y1 = std::min(y0 + 1, height - 1);
    const double wx = x - x0;
    const double wy = y - y0;
    for (int channel = 0; channel < 3; ++channel) {
        const double top = source[y0 * stride + x0 * 3 + channel] * (1.0 - wx)
                         + source[y0 * stride + x1 * 3 + channel] * wx;
        const double bottom = source[y1 * stride + x0 * 3 + channel] * (1.0 - wx)
                            + source[y1 * stride + x1 * 3 + channel] * wx;
        out[channel] = clamp_u8(static_cast<int>(std::lround(top * (1.0 - wy) + bottom * wy)));
    }
}

unsigned char bgr_to_y(unsigned char b, unsigned char g, unsigned char r) {
    return clamp_u8((38 * r + 75 * g + 15 * b + 64) >> 7);
}

unsigned char bgr_to_u(unsigned char b, unsigned char g, unsigned char r) {
    return clamp_u8(((-43 * r - 84 * g + 127 * b + 128) >> 8) + 128);
}

unsigned char bgr_to_v(unsigned char b, unsigned char g, unsigned char r) {
    return clamp_u8(((127 * r - 107 * g - 20 * b + 128) >> 8) + 128);
}

void set_error(std::string *error, const char *message) {
    if (error != nullptr) {
        *error = message;
    }
}

}  // namespace

bool compute_letterbox(
    int source_width,
    int source_height,
    int model_width,
    int model_height,
    LetterboxInfo *info,
    std::string *error) {
    if (info == nullptr || source_width <= 0 || source_height <= 0 || model_width <= 0 || model_height <= 0) {
        set_error(error, "image dimensions and output pointer must be valid");
        return false;
    }
    const double scale = std::min(
        static_cast<double>(model_width) / source_width,
        static_cast<double>(model_height) / source_height);
    const int resized_width = std::max(1, static_cast<int>(std::lround(source_width * scale)));
    const int resized_height = std::max(1, static_cast<int>(std::lround(source_height * scale)));
    info->source_width = source_width;
    info->source_height = source_height;
    info->model_width = model_width;
    info->model_height = model_height;
    info->resized_width = std::min(resized_width, model_width);
    info->resized_height = std::min(resized_height, model_height);
    info->scale = static_cast<float>(scale);
    info->pad_x = static_cast<float>((model_width - info->resized_width) / 2.0);
    info->pad_y = static_cast<float>((model_height - info->resized_height) / 2.0);
    if (error != nullptr) error->clear();
    return true;
}

void restore_box_to_source(
    const LetterboxInfo &info,
    double *x1,
    double *y1,
    double *x2,
    double *y2) {
    if (x1 == nullptr || y1 == nullptr || x2 == nullptr || y2 == nullptr || info.scale <= 0.0f) {
        return;
    }
    *x1 = clamp_double((*x1 - info.pad_x) / info.scale, 0.0, static_cast<double>(info.source_width - 1));
    *y1 = clamp_double((*y1 - info.pad_y) / info.scale, 0.0, static_cast<double>(info.source_height - 1));
    *x2 = clamp_double((*x2 - info.pad_x) / info.scale, 0.0, static_cast<double>(info.source_width - 1));
    *y2 = clamp_double((*y2 - info.pad_y) / info.scale, 0.0, static_cast<double>(info.source_height - 1));
}

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
    std::string *error) {
    if (source_bgr == nullptr || nv12 == nullptr || letterbox_bgr == nullptr || info == nullptr) {
        set_error(error, "source and output pointers must be non-null");
        return false;
    }
    if ((model_width & 1) != 0 || (model_height & 1) != 0) {
        set_error(error, "NV12 model dimensions must be even");
        return false;
    }
    if (source_stride < source_width * 3 || source_bytes < static_cast<std::size_t>(source_stride) * source_height) {
        set_error(error, "source BGR buffer is smaller than dimensions and stride require");
        return false;
    }
    if (!compute_letterbox(source_width, source_height, model_width, model_height, info, error)) {
        return false;
    }

    letterbox_bgr->assign(static_cast<std::size_t>(model_width) * model_height * 3, 114);
    const int offset_x = static_cast<int>(std::floor(info->pad_x));
    const int offset_y = static_cast<int>(std::floor(info->pad_y));
    for (int y = 0; y < info->resized_height; ++y) {
        const double source_y = (y + 0.5) / info->scale - 0.5;
        for (int x = 0; x < info->resized_width; ++x) {
            const double source_x = (x + 0.5) / info->scale - 0.5;
            unsigned char *destination = &(*letterbox_bgr)[
                (static_cast<std::size_t>(y + offset_y) * model_width + x + offset_x) * 3];
            sample_bilinear_bgr(source_bgr, source_width, source_height, source_stride, source_x, source_y, destination);
        }
    }

    const std::size_t y_bytes = static_cast<std::size_t>(model_width) * model_height;
    nv12->assign(y_bytes + y_bytes / 2, 0);
    for (int y = 0; y < model_height; ++y) {
        for (int x = 0; x < model_width; ++x) {
            const std::size_t pixel = (static_cast<std::size_t>(y) * model_width + x) * 3;
            (*nv12)[static_cast<std::size_t>(y) * model_width + x] = bgr_to_y(
                (*letterbox_bgr)[pixel], (*letterbox_bgr)[pixel + 1], (*letterbox_bgr)[pixel + 2]);
        }
    }
    for (int y = 0; y < model_height; y += 2) {
        for (int x = 0; x < model_width; x += 2) {
            int b_sum = 0;
            int g_sum = 0;
            int r_sum = 0;
            for (int dy = 0; dy < 2; ++dy) {
                for (int dx = 0; dx < 2; ++dx) {
                    const std::size_t pixel = (static_cast<std::size_t>(y + dy) * model_width + x + dx) * 3;
                    b_sum += (*letterbox_bgr)[pixel];
                    g_sum += (*letterbox_bgr)[pixel + 1];
                    r_sum += (*letterbox_bgr)[pixel + 2];
                }
            }
            const unsigned char b = static_cast<unsigned char>(b_sum / 4);
            const unsigned char g = static_cast<unsigned char>(g_sum / 4);
            const unsigned char r = static_cast<unsigned char>(r_sum / 4);
            const std::size_t uv = y_bytes + static_cast<std::size_t>(y / 2) * model_width + x;
            (*nv12)[uv] = bgr_to_u(b, g, r);
            (*nv12)[uv + 1] = bgr_to_v(b, g, r);
        }
    }
    if (error != nullptr) error->clear();
    return true;
}
