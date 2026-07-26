#include "frame_preprocess.h"

#include <cmath>
#include <cstdio>
#include <string>
#include <vector>

namespace {

int failures = 0;

void expect_true(bool value, const char *label) {
    if (!value) {
        std::fprintf(stderr, "%s: expected true\n", label);
        ++failures;
    }
}

void expect_equal(long long expected, long long actual, const char *label) {
    if (expected != actual) {
        std::fprintf(stderr, "%s: expected %lld got %lld\n", label, expected, actual);
        ++failures;
    }
}

void expect_near(double expected, double actual, double tolerance, const char *label) {
    if (std::fabs(expected - actual) > tolerance) {
        std::fprintf(stderr, "%s: expected %.6f got %.6f\n", label, expected, actual);
        ++failures;
    }
}

void test_letterbox_geometry() {
    LetterboxInfo wide{};
    std::string error;
    expect_true(compute_letterbox(1280, 720, 640, 640, &wide, &error), "wide letterbox");
    expect_equal(640, wide.resized_width, "wide resized width");
    expect_equal(360, wide.resized_height, "wide resized height");
    expect_near(0.5, wide.scale, 1e-6, "wide scale");
    expect_near(0.0, wide.pad_x, 1e-6, "wide pad x");
    expect_near(140.0, wide.pad_y, 1e-6, "wide pad y");

    LetterboxInfo tall{};
    expect_true(compute_letterbox(480, 640, 640, 640, &tall, &error), "tall letterbox");
    expect_equal(480, tall.resized_width, "tall resized width");
    expect_equal(640, tall.resized_height, "tall resized height");
    expect_near(80.0, tall.pad_x, 1e-6, "tall pad x");
    expect_near(0.0, tall.pad_y, 1e-6, "tall pad y");
}

void test_coordinate_restore() {
    LetterboxInfo info{};
    std::string error;
    expect_true(compute_letterbox(1280, 720, 640, 640, &info, &error), "restore setup");
    double x1 = 50.0;
    double y1 = 190.0;
    double x2 = 300.0;
    double y2 = 390.0;
    restore_box_to_source(info, &x1, &y1, &x2, &y2);
    expect_near(100.0, x1, 1e-6, "restore x1");
    expect_near(100.0, y1, 1e-6, "restore y1");
    expect_near(600.0, x2, 1e-6, "restore x2");
    expect_near(500.0, y2, 1e-6, "restore y2");
}

void test_black_and_white_nv12() {
    std::string error;
    LetterboxInfo info{};
    std::vector<unsigned char> preview;
    std::vector<unsigned char> nv12;

    std::vector<unsigned char> black(2 * 2 * 3, 0);
    expect_true(bgr_letterbox_to_nv12(black.data(), black.size(), 2, 2, 6, 4, 4, &nv12, &preview, &info, &error), "black conversion");
    expect_equal(24, static_cast<long long>(nv12.size()), "black nv12 size");
    for (int i = 0; i < 16; ++i) expect_equal(0, nv12[static_cast<std::size_t>(i)], "black y");
    for (std::size_t i = 16; i < nv12.size(); ++i) expect_equal(128, nv12[i], "black uv");

    std::vector<unsigned char> white(2 * 2 * 3, 255);
    expect_true(bgr_letterbox_to_nv12(white.data(), white.size(), 2, 2, 6, 4, 4, &nv12, &preview, &info, &error), "white conversion");
    for (int i = 0; i < 16; ++i) expect_equal(255, nv12[static_cast<std::size_t>(i)], "white y");

    std::vector<unsigned char> red(2 * 2 * 3, 0);
    for (std::size_t i = 0; i < red.size(); i += 3) red[i + 2] = 255;
    expect_true(bgr_letterbox_to_nv12(red.data(), red.size(), 2, 2, 6, 2, 2, &nv12, &preview, &info, &error), "red conversion");
    for (int i = 0; i < 4; ++i) expect_equal(76, nv12[static_cast<std::size_t>(i)], "red y");
    expect_equal(85, nv12[4], "red u");
    expect_equal(255, nv12[5], "red v");
}

void test_horizontal_padding_uses_gray_114() {
    std::vector<unsigned char> source(2 * 4 * 3, 255);
    std::vector<unsigned char> nv12;
    std::vector<unsigned char> preview;
    LetterboxInfo info{};
    std::string error;
    expect_true(bgr_letterbox_to_nv12(source.data(), source.size(), 4, 2, 12, 4, 4, &nv12, &preview, &info, &error), "wide padded conversion");
    expect_near(1.0, info.pad_y, 1e-6, "wide padded pad y");
    expect_equal(114, preview[0], "padding b");
    expect_equal(114, preview[1], "padding g");
    expect_equal(114, preview[2], "padding r");
    expect_equal(114, nv12[0], "padding y");
}

void test_rejects_bad_buffer_and_odd_model() {
    std::vector<unsigned char> source(12, 0);
    std::vector<unsigned char> nv12;
    std::vector<unsigned char> preview;
    LetterboxInfo info{};
    std::string error;
    expect_true(!bgr_letterbox_to_nv12(source.data(), 3, 2, 2, 6, 4, 4, &nv12, &preview, &info, &error), "short source rejected");
    expect_true(!bgr_letterbox_to_nv12(source.data(), source.size(), 2, 2, 6, 3, 4, &nv12, &preview, &info, &error), "odd model rejected");
}

}  // namespace

int main() {
    test_letterbox_geometry();
    test_coordinate_restore();
    test_black_and_white_nv12();
    test_horizontal_padding_uses_gray_114();
    test_rejects_bad_buffer_and_odd_model();
    if (failures != 0) {
        std::fprintf(stderr, "%d preprocess test failure(s)\n", failures);
        return 1;
    }
    std::printf("preprocess tests passed\n");
    return 0;
}
