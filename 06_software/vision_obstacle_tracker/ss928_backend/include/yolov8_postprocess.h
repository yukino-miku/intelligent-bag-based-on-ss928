#ifndef YOLOV8_POSTPROCESS_H
#define YOLOV8_POSTPROCESS_H

#include "frame_preprocess.h"
#include "vot_backend.h"

#include <cstddef>
#include <string>
#include <vector>

struct YoloV8DecodeStats {
    std::size_t anchors = 0;
    std::size_t raw_candidate_count = 0;
    std::size_t nms_detection_count = 0;
};

bool decode_yolov8(
    const float *output,
    std::size_t output_elements,
    const std::vector<long long> &dims,
    const LetterboxInfo &letterbox,
    const BackendTargetClassFilter &target_filter,
    float confidence_threshold,
    float nms_iou_threshold,
    int max_detections,
    std::vector<BackendDetection> *detections,
    YoloV8DecodeStats *stats,
    std::string *error);

#endif
