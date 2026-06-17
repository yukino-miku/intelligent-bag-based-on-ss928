#include "vot_backend.h"

#include <cmath>
#include <cstdio>
#include <string>
#include <vector>

static int failures = 0;

static void fail_at(const char *file, int line, const char *expr) {
    std::fprintf(stderr, "%s:%d: assertion failed: %s\n", file, line, expr);
    failures++;
}

#define ASSERT_TRUE(expr) do { if (!(expr)) fail_at(__FILE__, __LINE__, #expr); } while (0)
#define ASSERT_FALSE(expr) ASSERT_TRUE(!(expr))
#define ASSERT_INT_EQ(expected, actual) do { int e__ = (expected); int a__ = (actual); if (e__ != a__) { std::fprintf(stderr, "%s:%d: expected %d got %d\n", __FILE__, __LINE__, e__, a__); failures++; } } while (0)
#define ASSERT_NEAR(expected, actual, tol) do { double e__ = (expected); double a__ = (actual); double t__ = (tol); if (std::fabs(e__ - a__) > t__) { std::fprintf(stderr, "%s:%d: expected %.9f got %.9f tol %.9f\n", __FILE__, __LINE__, e__, a__, t__); failures++; } } while (0)

static BackendDetection make_detection(double x1, double y1, double x2, double y2, int class_id, float score) {
    BackendDetection detection{};
    detection.x1 = x1;
    detection.y1 = y1;
    detection.x2 = x2;
    detection.y2 = y2;
    detection.class_id = class_id;
    detection.score = score;
    return detection;
}

static void test_target_class_filter(void) {
    BackendTargetClassFilter filter = backend_parse_target_classes("car,bicycle,motorcycle,bus,truck");
    ASSERT_TRUE(backend_should_keep_class(filter, backend_coco_class_id("car")));
    ASSERT_TRUE(backend_should_keep_class(filter, backend_coco_class_id("bicycle")));
    ASSERT_FALSE(backend_should_keep_class(filter, backend_coco_class_id("person")));

    BackendTargetClassFilter all = backend_parse_target_classes("all");
    ASSERT_TRUE(backend_should_keep_class(all, backend_coco_class_id("person")));
}

static void test_nms_suppresses_same_class_overlap(void) {
    std::vector<BackendDetection> detections;
    detections.push_back(make_detection(0.0, 0.0, 100.0, 100.0, backend_coco_class_id("car"), 0.90f));
    detections.push_back(make_detection(5.0, 5.0, 105.0, 105.0, backend_coco_class_id("car"), 0.80f));
    detections.push_back(make_detection(200.0, 200.0, 260.0, 260.0, backend_coco_class_id("car"), 0.70f));

    std::vector<BackendDetection> kept = backend_nms(detections, 0.45f, 10);
    ASSERT_INT_EQ(2, static_cast<int>(kept.size()));
    ASSERT_NEAR(0.90, kept[0].score, 0.0001);
    ASSERT_NEAR(0.70, kept[1].score, 0.0001);
}

static void test_tracker_preserves_id_for_overlapping_detection(void) {
    BackendSimpleTracker tracker;
    std::vector<BackendDetection> first;
    first.push_back(make_detection(10.0, 10.0, 110.0, 110.0, backend_coco_class_id("car"), 0.90f));
    std::vector<BackendDetection> first_tracked = tracker.update(first);
    ASSERT_INT_EQ(1, static_cast<int>(first_tracked.size()));
    ASSERT_INT_EQ(1, first_tracked[0].track_id);

    std::vector<BackendDetection> second;
    second.push_back(make_detection(14.0, 12.0, 114.0, 112.0, backend_coco_class_id("car"), 0.85f));
    std::vector<BackendDetection> second_tracked = tracker.update(second);
    ASSERT_INT_EQ(1, static_cast<int>(second_tracked.size()));
    ASSERT_INT_EQ(first_tracked[0].track_id, second_tracked[0].track_id);

    std::vector<BackendDetection> third;
    third.push_back(make_detection(14.0, 12.0, 114.0, 112.0, backend_coco_class_id("bicycle"), 0.85f));
    std::vector<BackendDetection> third_tracked = tracker.update(third);
    ASSERT_INT_EQ(1, static_cast<int>(third_tracked.size()));
    ASSERT_TRUE(third_tracked[0].track_id != first_tracked[0].track_id);
}

int main() {
    test_target_class_filter();
    test_nms_suppresses_same_class_overlap();
    test_tracker_preserves_id_for_overlapping_detection();

    if (failures != 0) {
        std::fprintf(stderr, "%d backend test failure(s)\n", failures);
        return 1;
    }
    std::printf("C backend helper tests passed\n");
    return 0;
}
