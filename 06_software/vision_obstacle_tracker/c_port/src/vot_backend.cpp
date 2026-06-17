#include "vot_backend.h"

#include <algorithm>
#include <cctype>
#include <sstream>

namespace {

constexpr std::array<const char *, 80> kCocoNames = {
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
    "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench",
    "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
    "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove",
    "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup",
    "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
    "hair drier", "toothbrush",
};

std::string trim_ascii(std::string value) {
    auto not_space = [](unsigned char ch) { return !std::isspace(ch); };
    value.erase(value.begin(), std::find_if(value.begin(), value.end(), not_space));
    value.erase(std::find_if(value.rbegin(), value.rend(), not_space).base(), value.end());
    return value;
}

std::string lower_ascii(std::string value) {
    for (char &ch : value) {
        ch = static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
    }
    return value;
}

double box_area(const BackendDetection &box) {
    const double width = std::max(0.0, box.x2 - box.x1);
    const double height = std::max(0.0, box.y2 - box.y1);
    return width * height;
}

}  // namespace

int backend_coco_class_count() {
    return static_cast<int>(kCocoNames.size());
}

const char *backend_coco_class_name(int class_id) {
    if (class_id < 0 || class_id >= backend_coco_class_count()) {
        return "";
    }
    return kCocoNames[static_cast<size_t>(class_id)];
}

int backend_coco_class_id(const std::string &class_name) {
    const std::string wanted = lower_ascii(trim_ascii(class_name));
    for (size_t i = 0; i < kCocoNames.size(); i++) {
        if (wanted == kCocoNames[i]) {
            return static_cast<int>(i);
        }
    }
    return -1;
}

BackendTargetClassFilter backend_parse_target_classes(const std::string &value) {
    BackendTargetClassFilter filter;
    const std::string normalized = lower_ascii(trim_ascii(value));
    if (normalized == "all") {
        filter.all = true;
        filter.keep.fill(true);
        return filter;
    }

    std::stringstream stream(value);
    std::string item;
    while (std::getline(stream, item, ',')) {
        const int class_id = backend_coco_class_id(item);
        if (class_id >= 0) {
            filter.keep[static_cast<size_t>(class_id)] = true;
        }
    }
    return filter;
}

bool backend_should_keep_class(const BackendTargetClassFilter &filter, int class_id) {
    if (class_id < 0 || class_id >= backend_coco_class_count()) {
        return false;
    }
    return filter.all || filter.keep[static_cast<size_t>(class_id)];
}

double backend_box_iou(const BackendDetection &a, const BackendDetection &b) {
    const double ix1 = std::max(a.x1, b.x1);
    const double iy1 = std::max(a.y1, b.y1);
    const double ix2 = std::min(a.x2, b.x2);
    const double iy2 = std::min(a.y2, b.y2);
    const double intersection = std::max(0.0, ix2 - ix1) * std::max(0.0, iy2 - iy1);
    const double union_area = box_area(a) + box_area(b) - intersection;
    if (union_area <= 0.0) {
        return 0.0;
    }
    return intersection / union_area;
}

std::vector<BackendDetection> backend_nms(const std::vector<BackendDetection> &detections, float iou_threshold, int max_det) {
    std::vector<BackendDetection> ordered = detections;
    std::stable_sort(ordered.begin(), ordered.end(), [](const BackendDetection &left, const BackendDetection &right) {
        return left.score > right.score;
    });

    std::vector<BackendDetection> kept;
    for (const BackendDetection &candidate : ordered) {
        bool suppressed = false;
        for (const BackendDetection &existing : kept) {
            if (candidate.class_id == existing.class_id && backend_box_iou(candidate, existing) > iou_threshold) {
                suppressed = true;
                break;
            }
        }
        if (!suppressed) {
            kept.push_back(candidate);
            if (max_det > 0 && static_cast<int>(kept.size()) >= max_det) {
                break;
            }
        }
    }
    return kept;
}

std::vector<BackendDetection> BackendSimpleTracker::update(const std::vector<BackendDetection> &detections) {
    constexpr double kMinIou = 0.30;
    constexpr int kMaxMissed = 30;
    std::vector<BackendDetection> tracked;
    std::vector<bool> used_tracks(tracks_.size(), false);

    for (BackendDetection detection : detections) {
        int best_index = -1;
        double best_iou = 0.0;
        for (size_t i = 0; i < tracks_.size(); i++) {
            if (used_tracks[i] || tracks_[i].detection.class_id != detection.class_id) {
                continue;
            }
            const double iou = backend_box_iou(detection, tracks_[i].detection);
            if (iou > best_iou) {
                best_iou = iou;
                best_index = static_cast<int>(i);
            }
        }

        if (best_index >= 0 && best_iou >= kMinIou) {
            Track &track = tracks_[static_cast<size_t>(best_index)];
            detection.track_id = track.detection.track_id;
            track.detection = detection;
            track.missed = 0;
            used_tracks[static_cast<size_t>(best_index)] = true;
        } else {
            detection.track_id = next_track_id_++;
            Track track;
            track.detection = detection;
            track.missed = 0;
            tracks_.push_back(track);
            used_tracks.push_back(true);
        }
        tracked.push_back(detection);
    }

    for (size_t i = 0; i < tracks_.size(); i++) {
        if (!used_tracks[i]) {
            tracks_[i].missed++;
        }
    }
    tracks_.erase(
        std::remove_if(tracks_.begin(), tracks_.end(), [kMaxMissed](const Track &track) {
            return track.missed > kMaxMissed;
        }),
        tracks_.end()
    );

    return tracked;
}
