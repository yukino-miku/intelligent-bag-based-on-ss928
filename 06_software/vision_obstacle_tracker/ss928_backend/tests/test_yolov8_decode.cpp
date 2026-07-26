#include "frame_preprocess.h"
#include "vot_backend.h"
#include "yolov8_postprocess.h"

#include <cmath>
#include <cstdio>
#include <limits>
#include <string>
#include <vector>

namespace {

constexpr int kChannels = 84;
constexpr int kAnchors = 8400;
int failures = 0;

void expect_true(bool value, const char *label) {
    if (!value) {
        std::fprintf(stderr, "%s: expected true\n", label);
        ++failures;
    }
}

void expect_equal(int expected, int actual, const char *label) {
    if (expected != actual) {
        std::fprintf(stderr, "%s: expected %d got %d\n", label, expected, actual);
        ++failures;
    }
}

void expect_near(double expected, double actual, double tolerance, const char *label) {
    if (std::fabs(expected - actual) > tolerance) {
        std::fprintf(stderr, "%s: expected %.6f got %.6f\n", label, expected, actual);
        ++failures;
    }
}

void set_channel_first(std::vector<float> *output, int anchor, int channel, float value) {
    (*output)[static_cast<std::size_t>(channel) * kAnchors + anchor] = value;
}

void set_channel_last(std::vector<float> *output, int anchor, int channel, float value) {
    (*output)[static_cast<std::size_t>(anchor) * kChannels + channel] = value;
}

LetterboxInfo wide_letterbox() {
    LetterboxInfo info{};
    std::string error;
    compute_letterbox(1280, 720, 640, 640, &info, &error);
    return info;
}

BackendTargetClassFilter all_classes() {
    return backend_parse_target_classes("all");
}

void add_box_channel_first(
    std::vector<float> *output, int anchor, float cx, float cy, float width, float height,
    int class_id, float score) {
    set_channel_first(output, anchor, 0, cx);
    set_channel_first(output, anchor, 1, cy);
    set_channel_first(output, anchor, 2, width);
    set_channel_first(output, anchor, 3, height);
    set_channel_first(output, anchor, 4 + class_id, score);
}

void test_channel_first_and_coordinate_restore() {
    std::vector<float> output(static_cast<std::size_t>(kChannels) * kAnchors, 0.0f);
    add_box_channel_first(&output, 0, 320.0f, 320.0f, 200.0f, 100.0f, 2, 0.90f);
    std::vector<BackendDetection> detections;
    YoloV8DecodeStats stats{};
    std::string error;
    expect_true(decode_yolov8(output.data(), output.size(), {1, 84, 8400}, wide_letterbox(), all_classes(), 0.25f, 0.45f, 50, &detections, &stats, &error), "channel first decode");
    expect_equal(1, static_cast<int>(detections.size()), "channel first count");
    expect_equal(2, detections[0].class_id, "channel first class");
    expect_near(440.0, detections[0].x1, 1e-4, "channel first x1");
    expect_near(260.0, detections[0].y1, 1e-4, "channel first y1");
    expect_near(840.0, detections[0].x2, 1e-4, "channel first x2");
    expect_near(460.0, detections[0].y2, 1e-4, "channel first y2");
    expect_equal(1, static_cast<int>(stats.raw_candidate_count), "channel first raw candidates");
}

void test_class_aware_nms() {
    std::vector<float> output(static_cast<std::size_t>(kChannels) * kAnchors, 0.0f);
    add_box_channel_first(&output, 0, 320.0f, 320.0f, 200.0f, 200.0f, 2, 0.90f);
    add_box_channel_first(&output, 1, 325.0f, 325.0f, 200.0f, 200.0f, 2, 0.80f);
    add_box_channel_first(&output, 2, 320.0f, 320.0f, 200.0f, 200.0f, 1, 0.85f);
    std::vector<BackendDetection> detections;
    YoloV8DecodeStats stats{};
    std::string error;
    expect_true(decode_yolov8(output.data(), output.size(), {1, 84, 8400}, wide_letterbox(), all_classes(), 0.25f, 0.45f, 50, &detections, &stats, &error), "nms decode");
    expect_equal(2, static_cast<int>(detections.size()), "class aware nms count");
    expect_equal(3, static_cast<int>(stats.raw_candidate_count), "nms raw count");
}

void test_channel_last() {
    std::vector<float> output(static_cast<std::size_t>(kChannels) * kAnchors, 0.0f);
    set_channel_last(&output, 7, 0, 100.0f);
    set_channel_last(&output, 7, 1, 200.0f);
    set_channel_last(&output, 7, 2, 50.0f);
    set_channel_last(&output, 7, 3, 80.0f);
    set_channel_last(&output, 7, 4 + 7, 0.70f);
    std::vector<BackendDetection> detections;
    YoloV8DecodeStats stats{};
    std::string error;
    LetterboxInfo square{};
    compute_letterbox(640, 640, 640, 640, &square, &error);
    expect_true(decode_yolov8(output.data(), output.size(), {1, 8400, 84}, square, all_classes(), 0.25f, 0.45f, 50, &detections, &stats, &error), "channel last decode");
    expect_equal(1, static_cast<int>(detections.size()), "channel last count");
    expect_equal(7, detections[0].class_id, "channel last class");
}

void test_invalid_values_and_size() {
    std::vector<float> output(static_cast<std::size_t>(kChannels) * kAnchors, 0.0f);
    add_box_channel_first(&output, 0, std::numeric_limits<float>::quiet_NaN(), 10.0f, 20.0f, 20.0f, 2, 0.9f);
    add_box_channel_first(&output, 1, 10.0f, 10.0f, -20.0f, 20.0f, 2, 0.9f);
    add_box_channel_first(&output, 2, 10.0f, 10.0f, 20.0f, 20.0f, 2, std::numeric_limits<float>::infinity());
    std::vector<BackendDetection> detections;
    YoloV8DecodeStats stats{};
    std::string error;
    expect_true(decode_yolov8(output.data(), output.size(), {1, 84, 8400}, wide_letterbox(), all_classes(), 0.25f, 0.45f, 50, &detections, &stats, &error), "invalid values decode");
    expect_equal(0, static_cast<int>(detections.size()), "invalid values skipped");
    expect_true(!decode_yolov8(output.data(), output.size() - 1, {1, 84, 8400}, wide_letterbox(), all_classes(), 0.25f, 0.45f, 50, &detections, &stats, &error), "short output rejected");
    expect_true(!decode_yolov8(output.data(), output.size(), {1, 85, 8400}, wide_letterbox(), all_classes(), 0.25f, 0.45f, 50, &detections, &stats, &error), "wrong channels rejected");
}

}  // namespace

int main() {
    test_channel_first_and_coordinate_restore();
    test_class_aware_nms();
    test_channel_last();
    test_invalid_values_and_size();
    if (failures != 0) {
        std::fprintf(stderr, "%d YOLOv8 decode test failure(s)\n", failures);
        return 1;
    }
    std::printf("YOLOv8 decode tests passed\n");
    return 0;
}
