#ifndef VOT_H
#define VOT_H

#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

#define VOT_NAME_MAX 64
#define VOT_MAX_TRACKS 128
#define VOT_MAX_HISTORY 64
#define VOT_MAX_OBSERVATIONS 128
#define VOT_MJPEG_BUFFER_CAPACITY (8u * 1024u * 1024u)

typedef struct {
    double x1;
    double y1;
    double x2;
    double y2;
} VotBBox;

typedef struct {
    double x_m;
    double z_m;
} VotGroundPoint;

typedef struct {
    int image_width;
    int image_height;
    double fov_deg;
    char fov_type[VOT_NAME_MAX];
    bool has_horizontal_fov;
    double horizontal_fov_deg;
    double camera_height_m;
    double camera_pitch_deg;
    double distance_scale;
    bool has_principal_x;
    bool has_principal_y;
    double principal_x_px;
    double principal_y_px;
} VotCameraCalibration;

typedef struct {
    VotGroundPoint point;
    char source[VOT_NAME_MAX];
    bool has_ground_distance;
    double ground_distance_m;
    bool has_size_distance;
    double size_distance_m;
} VotDistanceEstimate;

typedef struct {
    int track_id;
    char class_name[VOT_NAME_MAX];
    double confidence;
    VotBBox bbox;
    bool has_ground_point;
    VotGroundPoint ground_point;
    double timestamp_s;
    char distance_source[VOT_NAME_MAX];
} VotDetectionObservation;

typedef struct {
    int track_id;
    char class_name[VOT_NAME_MAX];
    double confidence;
    VotBBox bbox;
    bool has_ground_point;
    VotGroundPoint ground_point;
    bool has_distance;
    double distance_m;
    double vx_mps;
    double vz_mps;
    double speed_mps;
    double timestamp_s;
    char distance_source[VOT_NAME_MAX];
} VotTrackedObject;

typedef struct {
    double trajectory;
    double ttc;
    double drac;
    double closing;
} VotRiskWeights;

typedef struct {
    double bicycle_safe_trajectory_distance_m;
    double motor_vehicle_safe_trajectory_distance_m;
    double emergency_ttc_s;
    double danger_ttc_s;
    double caution_ttc_s;
    double attention_ttc_s;
    double comfortable_decel_mps2;
    double emergency_decel_mps2;
    double max_closing_speed_mps;
    double trajectory_risk_exponent;
    VotRiskWeights weights;
} VotRiskModelConfig;

typedef enum {
    VOT_RISK_SAFE = 0,
    VOT_RISK_ATTENTION = 1,
    VOT_RISK_CAUTION = 2,
    VOT_RISK_DANGER = 3,
    VOT_RISK_EMERGENCY = 4
} VotRiskLevel;

typedef struct {
    int track_id;
    double score;
    VotRiskLevel level;
    bool has_ttc;
    double ttc_s;
    bool has_trajectory_distance;
    double trajectory_distance_m;
    double drac_mps2;
    double closing_speed_mps;
} VotRiskAssessment;

typedef struct {
    int b;
    int g;
    int r;
} VotBgr;

typedef struct {
    int min_warning_frames;
    struct {
        bool active;
        int track_id;
        int count;
    } entries[VOT_MAX_TRACKS];
} VotRiskWarningStabilizer;

typedef struct {
    VotGroundPoint point;
    double timestamp_s;
} VotTrackSample;

typedef struct {
    bool active;
    int track_id;
    bool has_smoothed_ground;
    VotGroundPoint smoothed_ground;
    size_t sample_count;
    VotTrackSample samples[VOT_MAX_HISTORY];
} VotTrackHistory;

typedef struct {
    double history_seconds;
    double smoothing_alpha;
    double max_speed_mps;
    double speed_scale;
    VotTrackHistory histories[VOT_MAX_TRACKS];
} VotTrackState;

typedef struct {
    bool active;
    int stable_id;
    int raw_track_id;
    char class_name[VOT_NAME_MAX];
    bool has_ground_point;
    VotGroundPoint ground_point;
    double timestamp_s;
} VotStableTrackMemory;

typedef struct {
    bool active;
    int raw_track_id;
    int stable_id;
} VotRawStableMap;

typedef struct {
    double max_match_distance_m;
    double max_time_gap_s;
    int next_stable_id;
    VotStableTrackMemory memories[VOT_MAX_TRACKS];
    VotRawStableMap raw_maps[VOT_MAX_TRACKS];
} VotStableTrackIdManager;

typedef struct {
    char source[VOT_NAME_MAX];
    char video[260];
    int camera_index;
    char camera_backend[VOT_NAME_MAX];
    char camera_name[VOT_NAME_MAX];
    char runtime_profile[VOT_NAME_MAX];
    int width;
    int height;
    double fps;
    char model[260];
    char tracker[260];
    double conf;
    int imgsz;
    int max_det;
    bool export_openvino;
    char target_classes[256];
    char device[VOT_NAME_MAX];
    double camera_height;
    double camera_pitch;
    double fov;
    char fov_type[VOT_NAME_MAX];
    bool has_horizontal_fov;
    double horizontal_fov;
    char distance_mode[VOT_NAME_MAX];
    double size_weight;
    double distance_scale;
    double speed_scale;
    double speed_window;
    double distance_smoothing;
    double max_speed;
    char enhance[VOT_NAME_MAX];
    double display_scale;
    char save_output[260];
    int max_frames;
    bool no_display;
    bool video_every_frame;
} VotRuntimeOptions;

typedef struct {
    unsigned char *data;
    size_t length;
} VotByteSpan;

typedef struct {
    unsigned char *buffer;
    size_t length;
    size_t capacity;
} VotMjpegFrameParser;

void vot_copy_class_name(char *dst, size_t dst_size, const char *src);
double vot_clamp(double value, double low, double high);
double vot_ground_distance(VotGroundPoint point);

VotCameraCalibration vot_camera_calibration_default(void);
double vot_camera_cx(const VotCameraCalibration *calibration);
double vot_camera_cy(const VotCameraCalibration *calibration);
double vot_camera_fx(const VotCameraCalibration *calibration);
double vot_camera_fy(const VotCameraCalibration *calibration);
bool vot_pixel_to_ground(double x_px, double y_px, const VotCameraCalibration *calibration, VotGroundPoint *out);
bool vot_estimate_size_distance_m(VotBBox bbox, const char *class_name, const VotCameraCalibration *calibration, double *out_distance_m);
bool vot_point_from_forward_distance(double x_px, double z_m, const VotCameraCalibration *calibration, VotGroundPoint *out);
bool vot_estimate_ground_point_from_bbox(VotBBox bbox, const char *class_name, const VotCameraCalibration *calibration, const char *mode, double size_weight, VotDistanceEstimate *out);

void vot_track_state_init(VotTrackState *state, double history_seconds, double smoothing_alpha, double max_speed_mps, double speed_scale);
VotTrackedObject vot_track_state_update(VotTrackState *state, VotDetectionObservation observation);
void vot_stable_track_id_manager_init(VotStableTrackIdManager *manager, double max_match_distance_m, double max_time_gap_s);
size_t vot_stable_track_assign(VotStableTrackIdManager *manager, const VotDetectionObservation *observations, size_t observation_count, VotDetectionObservation *out, size_t out_capacity);

VotRiskModelConfig vot_risk_model_config_default(void);
VotRiskLevel vot_risk_level_from_score(double score);
const char *vot_risk_level_name(VotRiskLevel level);
VotBgr vot_risk_color_bgr(VotRiskLevel level);
double vot_radial_closing_speed_mps(double x_m, double z_m, double vx_mps, double vz_mps);
double vot_trajectory_distance_m(double x_m, double z_m, double vx_mps, double vz_mps);
VotRiskAssessment vot_assess_collision_risk(VotTrackedObject target, const VotRiskModelConfig *config);

void vot_risk_warning_stabilizer_init(VotRiskWarningStabilizer *stabilizer, int min_warning_frames);
VotRiskAssessment vot_risk_warning_stabilize_one(VotRiskWarningStabilizer *stabilizer, VotRiskAssessment assessment);

VotRuntimeOptions vot_runtime_options_default(void);
bool vot_runtime_options_set_profile(VotRuntimeOptions *options, const char *profile);
bool vot_runtime_options_parse(VotRuntimeOptions *options, int argc, char **argv, char *error, size_t error_size);
bool vot_video_should_skip_frames(const VotRuntimeOptions *options);
int vot_display_wait_ms(const VotRuntimeOptions *options, double capture_fps);

void vot_mjpeg_parser_init(VotMjpegFrameParser *parser);
void vot_mjpeg_parser_destroy(VotMjpegFrameParser *parser);
size_t vot_mjpeg_parser_feed(VotMjpegFrameParser *parser, const unsigned char *chunk, size_t chunk_length, VotByteSpan *out_frames, size_t out_capacity);
void vot_mjpeg_parser_free_frames(VotByteSpan *frames, size_t frame_count);

#ifdef __cplusplus
}
#endif

#endif
