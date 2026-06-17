#ifndef VOT_BACKEND_H
#define VOT_BACKEND_H

#include <array>
#include <string>
#include <vector>

struct BackendDetection {
    double x1 = 0.0;
    double y1 = 0.0;
    double x2 = 0.0;
    double y2 = 0.0;
    int class_id = -1;
    float score = 0.0f;
    int track_id = 0;
};

struct BackendTargetClassFilter {
    bool all = false;
    std::array<bool, 80> keep{};
};

int backend_coco_class_count();
const char *backend_coco_class_name(int class_id);
int backend_coco_class_id(const std::string &class_name);

BackendTargetClassFilter backend_parse_target_classes(const std::string &value);
bool backend_should_keep_class(const BackendTargetClassFilter &filter, int class_id);

double backend_box_iou(const BackendDetection &a, const BackendDetection &b);
std::vector<BackendDetection> backend_nms(const std::vector<BackendDetection> &detections, float iou_threshold, int max_det);

class BackendSimpleTracker {
public:
    std::vector<BackendDetection> update(const std::vector<BackendDetection> &detections);

private:
    struct Track {
        BackendDetection detection;
        int missed = 0;
    };

    int next_track_id_ = 1;
    std::vector<Track> tracks_;
};

#endif
