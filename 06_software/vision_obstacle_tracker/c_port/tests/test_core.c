#include <math.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "vot.h"

static int failures = 0;

static void fail_at(const char *file, int line, const char *expr) {
    fprintf(stderr, "%s:%d: assertion failed: %s\n", file, line, expr);
    failures++;
}

#define ASSERT_TRUE(expr) do { if (!(expr)) fail_at(__FILE__, __LINE__, #expr); } while (0)
#define ASSERT_FALSE(expr) ASSERT_TRUE(!(expr))
#define ASSERT_INT_EQ(expected, actual) do { long e__ = (long)(expected); long a__ = (long)(actual); if (e__ != a__) { fprintf(stderr, "%s:%d: expected %ld got %ld\n", __FILE__, __LINE__, e__, a__); failures++; } } while (0)
#define ASSERT_STR_EQ(expected, actual) do { const char *e__ = (expected); const char *a__ = (actual); if (strcmp(e__, a__) != 0) { fprintf(stderr, "%s:%d: expected \"%s\" got \"%s\"\n", __FILE__, __LINE__, e__, a__); failures++; } } while (0)
#define ASSERT_NEAR(expected, actual, tol) do { double e__ = (expected); double a__ = (actual); double t__ = (tol); if (fabs(e__ - a__) > t__) { fprintf(stderr, "%s:%d: expected %.9f got %.9f tol %.9f\n", __FILE__, __LINE__, e__, a__, t__); failures++; } } while (0)
#define ASSERT_GT(left, right) do { double l__ = (left); double r__ = (right); if (!(l__ > r__)) { fprintf(stderr, "%s:%d: expected %.9f > %.9f\n", __FILE__, __LINE__, l__, r__); failures++; } } while (0)
#define ASSERT_LT(left, right) do { double l__ = (left); double r__ = (right); if (!(l__ < r__)) { fprintf(stderr, "%s:%d: expected %.9f < %.9f\n", __FILE__, __LINE__, l__, r__); failures++; } } while (0)

static VotDetectionObservation make_observation(
    int track_id,
    const char *class_name,
    double x_m,
    double z_m,
    double timestamp_s
) {
    VotDetectionObservation observation;
    memset(&observation, 0, sizeof(observation));
    observation.track_id = track_id;
    vot_copy_class_name(observation.class_name, sizeof(observation.class_name), class_name);
    observation.confidence = 0.90;
    observation.bbox = (VotBBox){0.0, 0.0, 10.0, 10.0};
    observation.has_ground_point = true;
    observation.ground_point = (VotGroundPoint){x_m, z_m};
    observation.timestamp_s = timestamp_s;
    vot_copy_class_name(observation.distance_source, sizeof(observation.distance_source), "fused");
    return observation;
}

static VotTrackedObject make_target(const char *class_name, double x_m, double z_m, double vx_mps, double vz_mps) {
    VotTrackedObject target;
    memset(&target, 0, sizeof(target));
    target.track_id = 1;
    vot_copy_class_name(target.class_name, sizeof(target.class_name), class_name);
    target.confidence = 0.90;
    target.bbox = (VotBBox){10.0, 10.0, 100.0, 100.0};
    target.has_ground_point = true;
    target.ground_point = (VotGroundPoint){x_m, z_m};
    target.has_distance = true;
    target.distance_m = vot_ground_distance(target.ground_point);
    target.vx_mps = vx_mps;
    target.vz_mps = vz_mps;
    target.speed_mps = hypot(vx_mps, vz_mps);
    target.timestamp_s = 1.0;
    vot_copy_class_name(target.distance_source, sizeof(target.distance_source), "fused");
    return target;
}

static void test_calibration(void) {
    VotCameraCalibration calibration = vot_camera_calibration_default();
    calibration.image_width = 1920;
    calibration.image_height = 1080;
    calibration.fov_deg = 120.0;
    vot_copy_class_name(calibration.fov_type, sizeof(calibration.fov_type), "diagonal");

    ASSERT_NEAR(635.6, vot_camera_fx(&calibration), 1.0);
    ASSERT_NEAR(vot_camera_fx(&calibration), vot_camera_fy(&calibration), 0.001);

    calibration.image_width = 2560;
    calibration.image_height = 1440;
    calibration.has_horizontal_fov = true;
    calibration.horizontal_fov_deg = 80.0;
    calibration.camera_height_m = 1.2;
    calibration.camera_pitch_deg = 12.0;
    VotGroundPoint point;
    ASSERT_TRUE(vot_pixel_to_ground(1280.0, 1300.0, &calibration, &point));
    ASSERT_NEAR(0.0, point.x_m, 0.05);
    ASSERT_GT(point.z_m, 0.5);
    ASSERT_LT(point.z_m, 10.0);

    ASSERT_FALSE(vot_pixel_to_ground(1280.0, 200.0, &calibration, &point));
}

static void test_distance_estimation(void) {
    VotCameraCalibration calibration = vot_camera_calibration_default();
    calibration.image_width = 1920;
    calibration.image_height = 1080;
    calibration.fov_deg = 120.0;
    vot_copy_class_name(calibration.fov_type, sizeof(calibration.fov_type), "diagonal");

    double distance_m = 0.0;
    ASSERT_TRUE(vot_estimate_size_distance_m((VotBBox){900.0, 500.0, 1020.0, 560.0}, "car", &calibration, &distance_m));
    ASSERT_GT(distance_m, 10.0);

    calibration.camera_height_m = 1.1;
    calibration.camera_pitch_deg = 5.0;
    VotDistanceEstimate estimate;
    ASSERT_TRUE(vot_estimate_ground_point_from_bbox(
        (VotBBox){900.0, 500.0, 1020.0, 560.0},
        "car",
        &calibration,
        "fused",
        0.75,
        &estimate
    ));
    ASSERT_STR_EQ("fused", estimate.source);
    ASSERT_GT(estimate.point.z_m, 8.0);
}

static void test_track_state(void) {
    VotTrackState state;
    vot_track_state_init(&state, 10.0, 1.0, 40.0, 1.0);
    vot_track_state_update(&state, make_observation(7, "car", 0.0, 8.0, 10.0));
    VotTrackedObject tracked = vot_track_state_update(&state, make_observation(7, "car", 1.0, 5.0, 11.0));

    ASSERT_NEAR(1.0, tracked.vx_mps, 0.001);
    ASSERT_NEAR(-3.0, tracked.vz_mps, 0.001);
    ASSERT_NEAR(3.162, tracked.speed_mps, 0.001);

    vot_track_state_init(&state, 2.0, 0.5, 40.0, 1.0);
    vot_track_state_update(&state, make_observation(5, "car", 0.0, 20.0, 0.0));
    tracked = vot_track_state_update(&state, make_observation(5, "car", 0.0, 10.0, 1.0));
    ASSERT_NEAR(15.0, tracked.distance_m, 0.001);
}

static void test_stable_track_ids(void) {
    VotStableTrackIdManager manager;
    vot_stable_track_id_manager_init(&manager, 2.0, 1.0);

    VotDetectionObservation first_in[1] = {make_observation(11, "car", 0.0, 18.0, 0.0)};
    VotDetectionObservation first_out[1];
    ASSERT_INT_EQ(1, (int)vot_stable_track_assign(&manager, first_in, 1, first_out, 1));

    VotDetectionObservation switched_in[1] = {make_observation(42, "car", 0.2, 17.2, 0.4)};
    VotDetectionObservation switched_out[1];
    ASSERT_INT_EQ(1, (int)vot_stable_track_assign(&manager, switched_in, 1, switched_out, 1));
    ASSERT_INT_EQ(first_out[0].track_id, switched_out[0].track_id);

    VotDetectionObservation bicycle_in[1] = {make_observation(99, "bicycle", 0.2, 17.2, 0.5)};
    VotDetectionObservation bicycle_out[1];
    ASSERT_INT_EQ(1, (int)vot_stable_track_assign(&manager, bicycle_in, 1, bicycle_out, 1));
    ASSERT_TRUE(first_out[0].track_id != bicycle_out[0].track_id);
}

static void test_risk_model(void) {
    VotRiskModelConfig config = vot_risk_model_config_default();

    VotRiskAssessment head_on = vot_assess_collision_risk(make_target("car", 0.0, 4.0, 0.0, -12.0), &config);
    ASSERT_INT_EQ(VOT_RISK_EMERGENCY, head_on.level);
    ASSERT_GT(head_on.score, 0.90);
    ASSERT_LT(head_on.ttc_s, 0.5);
    ASSERT_NEAR(0.0, head_on.trajectory_distance_m, 0.001);

    VotRiskAssessment vertical = vot_assess_collision_risk(make_target("car", 3.0, 4.0, 0.0, -4.0), &config);
    VotRiskAssessment diagonal = vot_assess_collision_risk(make_target("car", 3.0, 4.0, -3.0, -4.0), &config);
    ASSERT_NEAR(3.0, vertical.trajectory_distance_m, 0.001);
    ASSERT_NEAR(0.0, diagonal.trajectory_distance_m, 0.001);
    ASSERT_NEAR(5.0, diagonal.closing_speed_mps, 0.001);

    VotRiskAssessment bicycle_safe = vot_assess_collision_risk(make_target("bicycle", 1.6, 4.0, 0.0, -4.0), &config);
    ASSERT_INT_EQ(VOT_RISK_SAFE, bicycle_safe.level);

    VotRiskModelConfig trajectory_only = config;
    trajectory_only.weights = (VotRiskWeights){1.0, 0.0, 0.0, 0.0};
    VotRiskAssessment saturated = vot_assess_collision_risk(make_target("car", 1.5, 4.0, 0.0, -4.0), &trajectory_only);
    ASSERT_NEAR(0.75, saturated.score, 0.001);

    VotRiskAssessment receding = vot_assess_collision_risk(make_target("car", 0.0, 0.5, 0.0, 1.0), &trajectory_only);
    ASSERT_INT_EQ(VOT_RISK_SAFE, receding.level);
    ASSERT_NEAR(0.0, receding.score, 0.001);
    ASSERT_NEAR(0.0, receding.closing_speed_mps, 0.001);
}

static void test_overlay_stabilizer(void) {
    VotRiskWarningStabilizer stabilizer;
    vot_risk_warning_stabilizer_init(&stabilizer, 3);

    VotRiskAssessment warning = {0};
    warning.track_id = 7;
    warning.score = 0.92;
    warning.level = VOT_RISK_EMERGENCY;
    warning.has_ttc = true;
    warning.ttc_s = 0.5;
    warning.has_trajectory_distance = true;
    warning.trajectory_distance_m = 0.0;
    warning.drac_mps2 = 4.0;
    warning.closing_speed_mps = 8.0;

    VotRiskAssessment first = vot_risk_warning_stabilize_one(&stabilizer, warning);
    VotRiskAssessment second = vot_risk_warning_stabilize_one(&stabilizer, warning);
    VotRiskAssessment third = vot_risk_warning_stabilize_one(&stabilizer, warning);

    ASSERT_INT_EQ(VOT_RISK_SAFE, first.level);
    ASSERT_INT_EQ(VOT_RISK_SAFE, second.level);
    ASSERT_INT_EQ(VOT_RISK_EMERGENCY, third.level);
    ASSERT_NEAR(0.0, first.score, 0.001);
    ASSERT_NEAR(0.92, third.score, 0.001);

    VotRiskAssessment safe = warning;
    safe.level = VOT_RISK_SAFE;
    safe.score = 0.0;
    vot_risk_warning_stabilize_one(&stabilizer, safe);
    first = vot_risk_warning_stabilize_one(&stabilizer, warning);
    second = vot_risk_warning_stabilize_one(&stabilizer, warning);
    third = vot_risk_warning_stabilize_one(&stabilizer, warning);
    ASSERT_INT_EQ(VOT_RISK_SAFE, first.level);
    ASSERT_INT_EQ(VOT_RISK_SAFE, second.level);
    ASSERT_INT_EQ(VOT_RISK_EMERGENCY, third.level);
}

static void test_runtime_options(void) {
    VotRuntimeOptions options = vot_runtime_options_default();
    ASSERT_STR_EQ("camera", options.source);
    ASSERT_STR_EQ("ffmpeg", options.camera_backend);
    ASSERT_STR_EQ("balanced", options.runtime_profile);
    ASSERT_INT_EQ(1280, options.width);
    ASSERT_INT_EQ(720, options.height);
    ASSERT_STR_EQ("vehicle_botsort.yaml", options.tracker);
    ASSERT_INT_EQ(1024, options.imgsz);
    ASSERT_NEAR(0.02, options.conf, 0.000001);
    ASSERT_INT_EQ(50, options.max_det);
    ASSERT_FALSE(options.export_openvino);
    ASSERT_NEAR(1.0, options.display_scale, 0.000001);
    ASSERT_NEAR(1.2, options.camera_height, 0.000001);
    ASSERT_NEAR(120.0, options.fov, 0.000001);
    ASSERT_STR_EQ("diagonal", options.fov_type);
    ASSERT_NEAR(5.0, options.camera_pitch, 0.000001);
    ASSERT_STR_EQ("fused", options.distance_mode);
    ASSERT_STR_EQ("off", options.enhance);

    VotRuntimeOptions quality = vot_runtime_options_default();
    vot_runtime_options_set_profile(&quality, "quality");
    ASSERT_INT_EQ(1920, quality.width);
    ASSERT_INT_EQ(1080, quality.height);
    ASSERT_INT_EQ(1024, quality.imgsz);
    ASSERT_NEAR(0.02, quality.conf, 0.000001);
    ASSERT_INT_EQ(50, quality.max_det);

    char *argv[] = {
        "vision_obstacle_tracker_c.exe",
        "--width", "1920",
        "--height", "1080",
        "--imgsz", "864",
        "--runtime-profile", "realtime",
    };
    char error[128];
    VotRuntimeOptions parsed;
    ASSERT_TRUE(vot_runtime_options_parse(&parsed, (int)(sizeof(argv) / sizeof(argv[0])), argv, error, sizeof(error)));
    ASSERT_STR_EQ("realtime", parsed.runtime_profile);
    ASSERT_INT_EQ(1920, parsed.width);
    ASSERT_INT_EQ(1080, parsed.height);
    ASSERT_INT_EQ(864, parsed.imgsz);
    ASSERT_NEAR(0.03, parsed.conf, 0.000001);
}

static void test_mjpeg_parser(void) {
    VotMjpegFrameParser parser;
    vot_mjpeg_parser_init(&parser);

    const unsigned char bytes[] = {
        'j', 'u', 'n', 'k',
        0xff, 0xd8, 'o', 'n', 'e', 0xff, 0xd9,
        0xff, 0xd8, 't', 'w', 'o', 0xff, 0xd9
    };
    VotByteSpan frames[2];
    size_t frame_count = vot_mjpeg_parser_feed(&parser, bytes, sizeof(bytes), frames, 2);
    ASSERT_INT_EQ(2, (int)frame_count);
    ASSERT_INT_EQ(7, (int)frames[0].length);
    ASSERT_INT_EQ(7, (int)frames[1].length);
    ASSERT_TRUE(frames[0].data[0] == 0xff && frames[0].data[1] == 0xd8);
    ASSERT_TRUE(frames[1].data[0] == 0xff && frames[1].data[1] == 0xd8);

    vot_mjpeg_parser_free_frames(frames, frame_count);
}

int main(void) {
    test_calibration();
    test_distance_estimation();
    test_track_state();
    test_stable_track_ids();
    test_risk_model();
    test_overlay_stabilizer();
    test_runtime_options();
    test_mjpeg_parser();

    if (failures != 0) {
        fprintf(stderr, "%d test failure(s)\n", failures);
        return 1;
    }
    printf("C core tests passed\n");
    return 0;
}
