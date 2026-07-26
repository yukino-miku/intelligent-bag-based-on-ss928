#include "yolov8_postprocess.h"

#include <cmath>

namespace {

void set_error(std::string *error, const std::string &message) {
    if (error != nullptr) {
        *error = message;
    }
}

}  // namespace

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
    std::string *error) {
    if (output == nullptr || detections == nullptr || stats == nullptr) {
        set_error(error, "output, detections, and stats must be non-null");
        return false;
    }
    detections->clear();
    *stats = YoloV8DecodeStats{};
    if (dims.size() != 3 || dims[0] != 1) {
        set_error(error, "YOLOv8 output must have three dimensions with batch 1");
        return false;
    }

    bool channel_first = false;
    long long channels = 0;
    long long anchors = 0;
    if (dims[1] == 84 && dims[2] > 0) {
        channel_first = true;
        channels = dims[1];
        anchors = dims[2];
    } else if (dims[2] == 84 && dims[1] > 0) {
        channel_first = false;
        channels = dims[2];
        anchors = dims[1];
    } else {
        set_error(error, "factory COCO YOLOv8 output must be [1,84,N] or [1,N,84]");
        return false;
    }
    const std::size_t required_elements = static_cast<std::size_t>(channels) * static_cast<std::size_t>(anchors);
    if (output_elements != required_elements) {
        set_error(error, "output element count does not match descriptor dimensions");
        return false;
    }
    if (letterbox.scale <= 0.0f || letterbox.source_width <= 0 || letterbox.source_height <= 0) {
        set_error(error, "letterbox metadata is invalid");
        return false;
    }

    const auto value_at = [output, channel_first, anchors, channels](long long anchor, long long channel) -> float {
        if (channel_first) {
            return output[static_cast<std::size_t>(channel * anchors + anchor)];
        }
        return output[static_cast<std::size_t>(anchor * channels + channel)];
    };

    std::vector<BackendDetection> proposals;
    proposals.reserve(static_cast<std::size_t>(anchors < 1024 ? anchors : 1024));
    for (long long anchor = 0; anchor < anchors; ++anchor) {
        int best_class = -1;
        float best_score = -1.0f;
        for (int class_id = 0; class_id < 80; ++class_id) {
            const float score = value_at(anchor, 4 + class_id);
            if (score > best_score) {
                best_score = score;
                best_class = class_id;
            }
        }
        if (best_class < 0 || !std::isfinite(best_score) || best_score < confidence_threshold
            || !backend_should_keep_class(target_filter, best_class)) {
            continue;
        }

        const float cx = value_at(anchor, 0);
        const float cy = value_at(anchor, 1);
        const float width = value_at(anchor, 2);
        const float height = value_at(anchor, 3);
        if (!std::isfinite(cx) || !std::isfinite(cy) || !std::isfinite(width) || !std::isfinite(height)
            || width <= 0.0f || height <= 0.0f) {
            continue;
        }

        BackendDetection detection;
        detection.x1 = cx - width * 0.5;
        detection.y1 = cy - height * 0.5;
        detection.x2 = cx + width * 0.5;
        detection.y2 = cy + height * 0.5;
        restore_box_to_source(letterbox, &detection.x1, &detection.y1, &detection.x2, &detection.y2);
        detection.class_id = best_class;
        detection.score = best_score;
        detection.track_id = 0;
        if (std::isfinite(detection.x1) && std::isfinite(detection.y1)
            && std::isfinite(detection.x2) && std::isfinite(detection.y2)
            && detection.x2 > detection.x1 && detection.y2 > detection.y1) {
            proposals.push_back(detection);
        }
    }

    stats->anchors = static_cast<std::size_t>(anchors);
    stats->raw_candidate_count = proposals.size();
    *detections = backend_nms(proposals, nms_iou_threshold, max_detections);
    stats->nms_detection_count = detections->size();
    if (error != nullptr) error->clear();
    return true;
}
