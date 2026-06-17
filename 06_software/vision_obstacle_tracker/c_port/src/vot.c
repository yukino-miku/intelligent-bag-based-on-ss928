#include "vot.h"

#include <ctype.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

typedef struct {
    const char *class_name;
    double width_m;
    double height_m;
} VotObjectDimensions;

static const VotObjectDimensions OBJECT_DIMENSIONS[] = {
    {"bicycle", 0.6, 1.4},
    {"car", 1.8, 1.5},
    {"motorcycle", 0.8, 1.3},
    {"bus", 2.5, 3.0},
    {"truck", 2.5, 3.2},
};

static int vot_stricmp_ascii(const char *a, const char *b) {
    while (*a && *b) {
        int ca = tolower((unsigned char)*a);
        int cb = tolower((unsigned char)*b);
        if (ca != cb) {
            return ca - cb;
        }
        a++;
        b++;
    }
    return tolower((unsigned char)*a) - tolower((unsigned char)*b);
}

void vot_copy_class_name(char *dst, size_t dst_size, const char *src) {
    if (dst_size == 0) {
        return;
    }
    if (src == NULL) {
        src = "";
    }
    snprintf(dst, dst_size, "%s", src);
}

double vot_clamp(double value, double low, double high) {
    if (value < low) {
        return low;
    }
    if (value > high) {
        return high;
    }
    return value;
}

double vot_ground_distance(VotGroundPoint point) {
    return hypot(point.x_m, point.z_m);
}

VotCameraCalibration vot_camera_calibration_default(void) {
    VotCameraCalibration calibration;
    memset(&calibration, 0, sizeof(calibration));
    calibration.image_width = 2560;
    calibration.image_height = 1440;
    calibration.fov_deg = 120.0;
    vot_copy_class_name(calibration.fov_type, sizeof(calibration.fov_type), "diagonal");
    calibration.has_horizontal_fov = false;
    calibration.horizontal_fov_deg = 0.0;
    calibration.camera_height_m = 1.1;
    calibration.camera_pitch_deg = 5.0;
    calibration.distance_scale = 1.0;
    return calibration;
}

double vot_camera_cx(const VotCameraCalibration *calibration) {
    return calibration->has_principal_x ? calibration->principal_x_px : (double)calibration->image_width / 2.0;
}

double vot_camera_cy(const VotCameraCalibration *calibration) {
    return calibration->has_principal_y ? calibration->principal_y_px : (double)calibration->image_height / 2.0;
}

static double vot_camera_focal_length_px(const VotCameraCalibration *calibration) {
    const char *fov_type = calibration->fov_type;
    double fov_deg = calibration->fov_deg;
    double sensor_px = 0.0;

    if (calibration->has_horizontal_fov) {
        fov_type = "horizontal";
        fov_deg = calibration->horizontal_fov_deg;
    }

    if (vot_stricmp_ascii(fov_type, "horizontal") == 0) {
        sensor_px = (double)calibration->image_width;
    } else if (vot_stricmp_ascii(fov_type, "vertical") == 0) {
        sensor_px = (double)calibration->image_height;
    } else {
        sensor_px = hypot((double)calibration->image_width, (double)calibration->image_height);
    }

    return sensor_px / (2.0 * tan((fov_deg / 2.0) * M_PI / 180.0));
}

double vot_camera_fx(const VotCameraCalibration *calibration) {
    return vot_camera_focal_length_px(calibration);
}

double vot_camera_fy(const VotCameraCalibration *calibration) {
    return vot_camera_focal_length_px(calibration);
}

bool vot_pixel_to_ground(double x_px, double y_px, const VotCameraCalibration *calibration, VotGroundPoint *out) {
    double horizontal_angle = atan((x_px - vot_camera_cx(calibration)) / vot_camera_fx(calibration));
    double vertical_angle_down = atan((y_px - vot_camera_cy(calibration)) / vot_camera_fy(calibration));
    double ground_angle_down = calibration->camera_pitch_deg * M_PI / 180.0 + vertical_angle_down;
    double z_m;

    if (ground_angle_down <= 0.0) {
        return false;
    }

    z_m = calibration->camera_height_m / tan(ground_angle_down);
    if (z_m <= 0.0 || !isfinite(z_m)) {
        return false;
    }

    z_m *= calibration->distance_scale;
    out->z_m = z_m;
    out->x_m = z_m * tan(horizontal_angle);
    return true;
}

static bool vot_object_dimensions_for_class(const char *class_name, double *width_m, double *height_m) {
    size_t i;
    for (i = 0; i < sizeof(OBJECT_DIMENSIONS) / sizeof(OBJECT_DIMENSIONS[0]); i++) {
        if (strcmp(class_name, OBJECT_DIMENSIONS[i].class_name) == 0) {
            *width_m = OBJECT_DIMENSIONS[i].width_m;
            *height_m = OBJECT_DIMENSIONS[i].height_m;
            return true;
        }
    }
    return false;
}

static void vot_bbox_size_px(VotBBox bbox, double *width_px, double *height_px) {
    *width_px = fmax(0.0, bbox.x2 - bbox.x1);
    *height_px = fmax(0.0, bbox.y2 - bbox.y1);
}

bool vot_estimate_size_distance_m(VotBBox bbox, const char *class_name, const VotCameraCalibration *calibration, double *out_distance_m) {
    double width_m = 0.0;
    double height_m = 0.0;
    double bbox_width_px = 0.0;
    double bbox_height_px = 0.0;
    double candidates[2];
    size_t count = 0;
    double distance_m;

    if (!vot_object_dimensions_for_class(class_name, &width_m, &height_m)) {
        return false;
    }

    vot_bbox_size_px(bbox, &bbox_width_px, &bbox_height_px);
    if (bbox_height_px >= 8.0) {
        candidates[count++] = height_m * vot_camera_fy(calibration) / bbox_height_px;
    }
    if (bbox_width_px >= 8.0) {
        candidates[count++] = width_m * vot_camera_fx(calibration) / bbox_width_px;
    }
    if (count == 0) {
        return false;
    }

    if (count == 1) {
        distance_m = candidates[0];
    } else {
        distance_m = (candidates[0] + candidates[1]) / 2.0;
    }
    distance_m *= calibration->distance_scale;
    if (distance_m <= 0.0 || !isfinite(distance_m)) {
        return false;
    }

    *out_distance_m = distance_m;
    return true;
}

bool vot_point_from_forward_distance(double x_px, double z_m, const VotCameraCalibration *calibration, VotGroundPoint *out) {
    double horizontal_angle;
    if (z_m <= 0.0 || !isfinite(z_m)) {
        return false;
    }
    horizontal_angle = atan((x_px - vot_camera_cx(calibration)) / vot_camera_fx(calibration));
    out->z_m = z_m;
    out->x_m = z_m * tan(horizontal_angle);
    return true;
}

bool vot_estimate_ground_point_from_bbox(VotBBox bbox, const char *class_name, const VotCameraCalibration *calibration, const char *mode, double size_weight, VotDistanceEstimate *out) {
    double bottom_x = (bbox.x1 + bbox.x2) / 2.0;
    double bottom_y = bbox.y2;
    double center_x = (bbox.x1 + bbox.x2) / 2.0;
    VotGroundPoint ground_point;
    VotGroundPoint size_point = {0.0, 0.0};
    bool has_ground = vot_pixel_to_ground(bottom_x, bottom_y, calibration, &ground_point);
    double size_distance_m = 0.0;
    bool has_size_distance = vot_estimate_size_distance_m(bbox, class_name, calibration, &size_distance_m);
    bool has_size_point = has_size_distance && vot_point_from_forward_distance(center_x, size_distance_m, calibration, &size_point);

    memset(out, 0, sizeof(*out));

    if (vot_stricmp_ascii(mode, "ground") == 0) {
        if (!has_ground) {
            return false;
        }
        out->point = ground_point;
        vot_copy_class_name(out->source, sizeof(out->source), "ground");
        out->has_ground_distance = true;
        out->ground_distance_m = vot_ground_distance(ground_point);
        out->has_size_distance = has_size_distance;
        out->size_distance_m = size_distance_m;
        return true;
    }

    if (vot_stricmp_ascii(mode, "size") == 0) {
        if (!has_size_point) {
            return false;
        }
        out->point = size_point;
        vot_copy_class_name(out->source, sizeof(out->source), "size");
        out->has_ground_distance = has_ground;
        out->ground_distance_m = has_ground ? vot_ground_distance(ground_point) : 0.0;
        out->has_size_distance = true;
        out->size_distance_m = size_distance_m;
        return true;
    }

    if (vot_stricmp_ascii(mode, "fused") != 0) {
        return false;
    }

    if (has_ground && has_size_point) {
        double clamped_weight = vot_clamp(size_weight, 0.0, 1.0);
        double z_m = ground_point.z_m * (1.0 - clamped_weight) + size_point.z_m * clamped_weight;
        if (!vot_point_from_forward_distance(center_x, z_m, calibration, &out->point)) {
            return false;
        }
        vot_copy_class_name(out->source, sizeof(out->source), "fused");
        out->has_ground_distance = true;
        out->ground_distance_m = vot_ground_distance(ground_point);
        out->has_size_distance = true;
        out->size_distance_m = size_distance_m;
        return true;
    }
    if (has_size_point) {
        out->point = size_point;
        vot_copy_class_name(out->source, sizeof(out->source), "size");
        out->has_size_distance = true;
        out->size_distance_m = size_distance_m;
        return true;
    }
    if (has_ground) {
        out->point = ground_point;
        vot_copy_class_name(out->source, sizeof(out->source), "ground");
        out->has_ground_distance = true;
        out->ground_distance_m = vot_ground_distance(ground_point);
        return true;
    }
    return false;
}

void vot_track_state_init(VotTrackState *state, double history_seconds, double smoothing_alpha, double max_speed_mps, double speed_scale) {
    memset(state, 0, sizeof(*state));
    state->history_seconds = history_seconds;
    state->smoothing_alpha = vot_clamp(smoothing_alpha, 0.0, 1.0);
    state->max_speed_mps = max_speed_mps;
    state->speed_scale = speed_scale;
}

static VotTrackHistory *vot_track_history_for_id(VotTrackState *state, int track_id) {
    size_t i;
    VotTrackHistory *empty = NULL;
    for (i = 0; i < VOT_MAX_TRACKS; i++) {
        if (state->histories[i].active && state->histories[i].track_id == track_id) {
            return &state->histories[i];
        }
        if (!state->histories[i].active && empty == NULL) {
            empty = &state->histories[i];
        }
    }
    if (empty == NULL) {
        empty = &state->histories[0];
    }
    memset(empty, 0, sizeof(*empty));
    empty->active = true;
    empty->track_id = track_id;
    return empty;
}

static VotGroundPoint vot_smooth_point(VotTrackState *state, VotTrackHistory *history, VotGroundPoint point) {
    VotGroundPoint smoothed;
    double alpha;
    (void)state;
    if (!history->has_smoothed_ground || state->smoothing_alpha >= 1.0) {
        history->smoothed_ground = point;
        history->has_smoothed_ground = true;
        return point;
    }
    alpha = state->smoothing_alpha;
    smoothed.x_m = history->smoothed_ground.x_m * (1.0 - alpha) + point.x_m * alpha;
    smoothed.z_m = history->smoothed_ground.z_m * (1.0 - alpha) + point.z_m * alpha;
    history->smoothed_ground = smoothed;
    return smoothed;
}

static void vot_history_append(VotTrackHistory *history, VotGroundPoint point, double timestamp_s) {
    if (history->sample_count >= VOT_MAX_HISTORY) {
        memmove(&history->samples[0], &history->samples[1], sizeof(history->samples[0]) * (VOT_MAX_HISTORY - 1));
        history->sample_count = VOT_MAX_HISTORY - 1;
    }
    history->samples[history->sample_count].point = point;
    history->samples[history->sample_count].timestamp_s = timestamp_s;
    history->sample_count++;
}

VotTrackedObject vot_track_state_update(VotTrackState *state, VotDetectionObservation observation) {
    VotTrackedObject tracked;
    double vx_mps = 0.0;
    double vz_mps = 0.0;
    double speed_mps = 0.0;
    VotGroundPoint output_point = observation.ground_point;
    bool has_distance = false;
    double distance_m = 0.0;

    memset(&tracked, 0, sizeof(tracked));

    if (observation.has_ground_point) {
        VotTrackHistory *history = vot_track_history_for_id(state, observation.track_id);
        double min_time;
        output_point = vot_smooth_point(state, history, observation.ground_point);
        distance_m = vot_ground_distance(output_point);
        has_distance = true;
        vot_history_append(history, output_point, observation.timestamp_s);
        min_time = observation.timestamp_s - state->history_seconds;
        while (history->sample_count > 2 && history->samples[0].timestamp_s < min_time) {
            memmove(&history->samples[0], &history->samples[1], sizeof(history->samples[0]) * (history->sample_count - 1));
            history->sample_count--;
        }
        if (history->sample_count >= 2) {
            VotTrackSample first = history->samples[0];
            VotTrackSample last = history->samples[history->sample_count - 1];
            double dt_s = last.timestamp_s - first.timestamp_s;
            if (dt_s > 0.0) {
                vx_mps = (last.point.x_m - first.point.x_m) / dt_s * state->speed_scale;
                vz_mps = (last.point.z_m - first.point.z_m) / dt_s * state->speed_scale;
            }
        }
    }

    speed_mps = hypot(vx_mps, vz_mps);
    if (state->max_speed_mps > 0.0 && speed_mps > state->max_speed_mps) {
        vx_mps = 0.0;
        vz_mps = 0.0;
        speed_mps = 0.0;
    }

    tracked.track_id = observation.track_id;
    vot_copy_class_name(tracked.class_name, sizeof(tracked.class_name), observation.class_name);
    tracked.confidence = observation.confidence;
    tracked.bbox = observation.bbox;
    tracked.has_ground_point = observation.has_ground_point;
    tracked.ground_point = output_point;
    tracked.has_distance = has_distance;
    tracked.distance_m = distance_m;
    tracked.vx_mps = vx_mps;
    tracked.vz_mps = vz_mps;
    tracked.speed_mps = speed_mps;
    tracked.timestamp_s = observation.timestamp_s;
    vot_copy_class_name(tracked.distance_source, sizeof(tracked.distance_source), observation.distance_source);
    return tracked;
}

void vot_stable_track_id_manager_init(VotStableTrackIdManager *manager, double max_match_distance_m, double max_time_gap_s) {
    memset(manager, 0, sizeof(*manager));
    manager->max_match_distance_m = max_match_distance_m;
    manager->max_time_gap_s = max_time_gap_s;
    manager->next_stable_id = 1;
}

static bool vot_assigned_contains(const int *assigned, size_t assigned_count, int stable_id) {
    size_t i;
    for (i = 0; i < assigned_count; i++) {
        if (assigned[i] == stable_id) {
            return true;
        }
    }
    return false;
}

static VotStableTrackMemory *vot_memory_by_stable_id(VotStableTrackIdManager *manager, int stable_id) {
    size_t i;
    for (i = 0; i < VOT_MAX_TRACKS; i++) {
        if (manager->memories[i].active && manager->memories[i].stable_id == stable_id) {
            return &manager->memories[i];
        }
    }
    return NULL;
}

static int vot_stable_id_for_raw_track(VotStableTrackIdManager *manager, const VotDetectionObservation *observation) {
    size_t i;
    for (i = 0; i < VOT_MAX_TRACKS; i++) {
        if (manager->raw_maps[i].active && manager->raw_maps[i].raw_track_id == observation->track_id) {
            VotStableTrackMemory *memory = vot_memory_by_stable_id(manager, manager->raw_maps[i].stable_id);
            if (memory != NULL && strcmp(memory->class_name, observation->class_name) == 0) {
                return manager->raw_maps[i].stable_id;
            }
        }
    }
    return 0;
}

static int vot_match_recent_track(VotStableTrackIdManager *manager, const VotDetectionObservation *observation, const int *assigned, size_t assigned_count) {
    int best_stable_id = 0;
    double best_distance = INFINITY;
    size_t i;

    if (!observation->has_ground_point) {
        return 0;
    }

    for (i = 0; i < VOT_MAX_TRACKS; i++) {
        VotStableTrackMemory *memory = &manager->memories[i];
        double time_gap;
        double distance;
        if (!memory->active || vot_assigned_contains(assigned, assigned_count, memory->stable_id)) {
            continue;
        }
        if (strcmp(memory->class_name, observation->class_name) != 0 || !memory->has_ground_point) {
            continue;
        }
        time_gap = observation->timestamp_s - memory->timestamp_s;
        if (time_gap < 0.0 || time_gap > manager->max_time_gap_s) {
            continue;
        }
        distance = hypot(observation->ground_point.x_m - memory->ground_point.x_m, observation->ground_point.z_m - memory->ground_point.z_m);
        if (distance <= manager->max_match_distance_m && distance < best_distance) {
            best_distance = distance;
            best_stable_id = memory->stable_id;
        }
    }
    return best_stable_id;
}

static void vot_update_raw_map(VotStableTrackIdManager *manager, int raw_track_id, int stable_id) {
    size_t i;
    for (i = 0; i < VOT_MAX_TRACKS; i++) {
        if (manager->raw_maps[i].active && manager->raw_maps[i].raw_track_id == raw_track_id) {
            manager->raw_maps[i].stable_id = stable_id;
            return;
        }
    }
    for (i = 0; i < VOT_MAX_TRACKS; i++) {
        if (!manager->raw_maps[i].active) {
            manager->raw_maps[i].active = true;
            manager->raw_maps[i].raw_track_id = raw_track_id;
            manager->raw_maps[i].stable_id = stable_id;
            return;
        }
    }
}

static void vot_update_memory(VotStableTrackIdManager *manager, int stable_id, const VotDetectionObservation *observation) {
    VotStableTrackMemory *slot = vot_memory_by_stable_id(manager, stable_id);
    size_t i;
    if (slot == NULL) {
        for (i = 0; i < VOT_MAX_TRACKS; i++) {
            if (!manager->memories[i].active) {
                slot = &manager->memories[i];
                break;
            }
        }
    }
    if (slot == NULL) {
        slot = &manager->memories[0];
    }
    memset(slot, 0, sizeof(*slot));
    slot->active = true;
    slot->stable_id = stable_id;
    slot->raw_track_id = observation->track_id;
    vot_copy_class_name(slot->class_name, sizeof(slot->class_name), observation->class_name);
    slot->has_ground_point = observation->has_ground_point;
    slot->ground_point = observation->ground_point;
    slot->timestamp_s = observation->timestamp_s;
}

static void vot_prune_old_memory(VotStableTrackIdManager *manager, const VotDetectionObservation *observations, size_t observation_count) {
    double newest_timestamp = observations[0].timestamp_s;
    double stale_before;
    int stale_ids[VOT_MAX_TRACKS];
    size_t stale_count = 0;
    size_t i;
    size_t j;

    if (observation_count == 0) {
        return;
    }
    for (i = 1; i < observation_count; i++) {
        if (observations[i].timestamp_s > newest_timestamp) {
            newest_timestamp = observations[i].timestamp_s;
        }
    }
    stale_before = newest_timestamp - manager->max_time_gap_s * 4.0;
    for (i = 0; i < VOT_MAX_TRACKS; i++) {
        if (manager->memories[i].active && manager->memories[i].timestamp_s < stale_before) {
            stale_ids[stale_count++] = manager->memories[i].stable_id;
            manager->memories[i].active = false;
        }
    }
    for (i = 0; i < VOT_MAX_TRACKS; i++) {
        if (!manager->raw_maps[i].active) {
            continue;
        }
        for (j = 0; j < stale_count; j++) {
            if (manager->raw_maps[i].stable_id == stale_ids[j]) {
                manager->raw_maps[i].active = false;
                break;
            }
        }
    }
}

size_t vot_stable_track_assign(VotStableTrackIdManager *manager, const VotDetectionObservation *observations, size_t observation_count, VotDetectionObservation *out, size_t out_capacity) {
    int assigned[VOT_MAX_OBSERVATIONS];
    size_t assigned_count = 0;
    size_t output_count = 0;
    size_t i;

    for (i = 0; i < observation_count && output_count < out_capacity; i++) {
        VotDetectionObservation stable_observation = observations[i];
        int stable_id = vot_stable_id_for_raw_track(manager, &observations[i]);
        if (stable_id == 0 || vot_assigned_contains(assigned, assigned_count, stable_id)) {
            stable_id = vot_match_recent_track(manager, &observations[i], assigned, assigned_count);
        }
        if (stable_id == 0) {
            stable_id = manager->next_stable_id++;
        }
        vot_update_raw_map(manager, observations[i].track_id, stable_id);
        if (assigned_count < VOT_MAX_OBSERVATIONS) {
            assigned[assigned_count++] = stable_id;
        }
        vot_update_memory(manager, stable_id, &observations[i]);
        stable_observation.track_id = stable_id;
        out[output_count++] = stable_observation;
    }
    vot_prune_old_memory(manager, observations, observation_count);
    return output_count;
}

VotRiskModelConfig vot_risk_model_config_default(void) {
    VotRiskModelConfig config;
    memset(&config, 0, sizeof(config));
    config.bicycle_safe_trajectory_distance_m = 1.5;
    config.motor_vehicle_safe_trajectory_distance_m = 3.0;
    config.emergency_ttc_s = 1.50;
    config.danger_ttc_s = 2.50;
    config.caution_ttc_s = 3.50;
    config.attention_ttc_s = 4.50;
    config.comfortable_decel_mps2 = 3.5;
    config.emergency_decel_mps2 = 7.0;
    config.max_closing_speed_mps = 12.0;
    config.trajectory_risk_exponent = 2.0;
    config.weights = (VotRiskWeights){4.0, 2.0, 1.5, 1.5};
    return config;
}

VotRiskLevel vot_risk_level_from_score(double score) {
    if (score >= 0.70) {
        return VOT_RISK_EMERGENCY;
    }
    if (score >= 0.60) {
        return VOT_RISK_DANGER;
    }
    if (score >= 0.50) {
        return VOT_RISK_CAUTION;
    }
    if (score >= 0.40) {
        return VOT_RISK_ATTENTION;
    }
    return VOT_RISK_SAFE;
}

const char *vot_risk_level_name(VotRiskLevel level) {
    switch (level) {
        case VOT_RISK_ATTENTION: return "ATTENTION";
        case VOT_RISK_CAUTION: return "CAUTION";
        case VOT_RISK_DANGER: return "DANGER";
        case VOT_RISK_EMERGENCY: return "EMERGENCY";
        case VOT_RISK_SAFE:
        default:
            return "SAFE";
    }
}

VotBgr vot_risk_color_bgr(VotRiskLevel level) {
    switch (level) {
        case VOT_RISK_ATTENTION: return (VotBgr){0, 255, 255};
        case VOT_RISK_CAUTION: return (VotBgr){0, 191, 255};
        case VOT_RISK_DANGER: return (VotBgr){0, 80, 255};
        case VOT_RISK_EMERGENCY: return (VotBgr){0, 0, 255};
        case VOT_RISK_SAFE:
        default:
            return (VotBgr){40, 220, 40};
    }
}

static bool vot_is_motor_vehicle(const char *class_name) {
    return strcmp(class_name, "car") == 0 || strcmp(class_name, "motorcycle") == 0 || strcmp(class_name, "truck") == 0 || strcmp(class_name, "bus") == 0;
}

static double vot_trajectory_safe_distance_threshold_m(const char *class_name, const VotRiskModelConfig *config) {
    if (strcmp(class_name, "bicycle") == 0) {
        return config->bicycle_safe_trajectory_distance_m;
    }
    if (vot_is_motor_vehicle(class_name)) {
        return config->motor_vehicle_safe_trajectory_distance_m;
    }
    return config->motor_vehicle_safe_trajectory_distance_m;
}

static bool vot_time_to_collision_s(double distance_m, bool has_distance, double closing_speed_mps, double *out) {
    if (!has_distance || closing_speed_mps <= 0.05) {
        return false;
    }
    *out = distance_m / closing_speed_mps;
    return true;
}

static double vot_decel_required_mps2(double distance_m, bool has_distance, double closing_speed_mps) {
    if (!has_distance || distance_m <= 0.05 || closing_speed_mps <= 0.05) {
        return 0.0;
    }
    return closing_speed_mps * closing_speed_mps / (2.0 * distance_m);
}

double vot_radial_closing_speed_mps(double x_m, double z_m, double vx_mps, double vz_mps) {
    double distance_m = hypot(x_m, z_m);
    if (distance_m <= 1e-6) {
        return fmax(0.0, -vz_mps);
    }
    return fmax(0.0, -((x_m * vx_mps + z_m * vz_mps) / distance_m));
}

double vot_trajectory_distance_m(double x_m, double z_m, double vx_mps, double vz_mps) {
    double speed = hypot(vx_mps, vz_mps);
    if (speed <= 1e-6) {
        return hypot(x_m, z_m);
    }
    return fabs(x_m * vz_mps - z_m * vx_mps) / speed;
}

static double vot_collision_time_risk(bool has_time, double time_s, const VotRiskModelConfig *config) {
    if (!has_time) {
        return 0.0;
    }
    if (time_s <= config->emergency_ttc_s) {
        return 1.0;
    }
    if (time_s <= config->danger_ttc_s) {
        return 0.82;
    }
    if (time_s <= config->caution_ttc_s) {
        return 0.62;
    }
    if (time_s <= config->attention_ttc_s) {
        return 0.52;
    }
    return 0.0;
}

static double vot_trajectory_distance_risk(double trajectory_distance, double safe_distance_m, double exponent) {
    double normalized_distance;
    if (safe_distance_m <= 1e-6) {
        return 0.0;
    }
    normalized_distance = vot_clamp(trajectory_distance / safe_distance_m, 0.0, 1.0);
    return vot_clamp(1.0 - pow(normalized_distance, fmax(exponent, 1e-6)), 0.0, 1.0);
}

VotRiskAssessment vot_assess_collision_risk(VotTrackedObject target, const VotRiskModelConfig *config_ptr) {
    VotRiskModelConfig default_config = vot_risk_model_config_default();
    const VotRiskModelConfig *config = config_ptr != NULL ? config_ptr : &default_config;
    VotRiskAssessment assessment;
    double trajectory_distance;
    double safe_trajectory_distance;
    double closing_speed;
    double ttc = 0.0;
    bool has_ttc;
    double drac;
    double trajectory_risk;
    double ttc_risk;
    double drac_risk;
    double closing_risk;
    double total_weight;
    double score;

    memset(&assessment, 0, sizeof(assessment));
    assessment.track_id = target.track_id;
    assessment.level = VOT_RISK_SAFE;

    if (!target.has_ground_point || !target.has_distance) {
        return assessment;
    }

    trajectory_distance = vot_trajectory_distance_m(target.ground_point.x_m, target.ground_point.z_m, target.vx_mps, target.vz_mps);
    assessment.has_trajectory_distance = true;
    assessment.trajectory_distance_m = trajectory_distance;

    if (target.vz_mps >= 0.0) {
        return assessment;
    }

    safe_trajectory_distance = vot_trajectory_safe_distance_threshold_m(target.class_name, config);
    closing_speed = vot_radial_closing_speed_mps(target.ground_point.x_m, target.ground_point.z_m, target.vx_mps, target.vz_mps);
    has_ttc = vot_time_to_collision_s(target.distance_m, target.has_distance, closing_speed, &ttc);
    drac = vot_decel_required_mps2(target.distance_m, target.has_distance, closing_speed);

    assessment.has_ttc = has_ttc;
    assessment.ttc_s = ttc;
    assessment.drac_mps2 = drac;
    assessment.closing_speed_mps = closing_speed;

    if (trajectory_distance > safe_trajectory_distance) {
        return assessment;
    }

    trajectory_risk = vot_trajectory_distance_risk(trajectory_distance, safe_trajectory_distance, config->trajectory_risk_exponent);
    ttc_risk = vot_collision_time_risk(has_ttc, ttc, config);
    drac_risk = vot_clamp((drac - config->comfortable_decel_mps2) / fmax(config->emergency_decel_mps2 - config->comfortable_decel_mps2, 0.1), 0.0, 1.0);
    closing_risk = vot_clamp(closing_speed / config->max_closing_speed_mps, 0.0, 1.0);

    total_weight = fmax(config->weights.trajectory + config->weights.ttc + config->weights.drac + config->weights.closing, 1e-6);
    score = vot_clamp(
        (
            config->weights.trajectory * trajectory_risk
            + config->weights.ttc * ttc_risk
            + config->weights.drac * drac_risk
            + config->weights.closing * closing_risk
        ) / total_weight,
        0.0,
        1.0
    );

    assessment.score = score;
    assessment.level = vot_risk_level_from_score(score);
    return assessment;
}

void vot_risk_warning_stabilizer_init(VotRiskWarningStabilizer *stabilizer, int min_warning_frames) {
    memset(stabilizer, 0, sizeof(*stabilizer));
    stabilizer->min_warning_frames = min_warning_frames < 1 ? 1 : min_warning_frames;
}

static int *vot_warning_count_for_track(VotRiskWarningStabilizer *stabilizer, int track_id, bool create) {
    size_t i;
    for (i = 0; i < VOT_MAX_TRACKS; i++) {
        if (stabilizer->entries[i].active && stabilizer->entries[i].track_id == track_id) {
            return &stabilizer->entries[i].count;
        }
    }
    if (!create) {
        return NULL;
    }
    for (i = 0; i < VOT_MAX_TRACKS; i++) {
        if (!stabilizer->entries[i].active) {
            stabilizer->entries[i].active = true;
            stabilizer->entries[i].track_id = track_id;
            stabilizer->entries[i].count = 0;
            return &stabilizer->entries[i].count;
        }
    }
    return &stabilizer->entries[0].count;
}

static void vot_warning_remove_track(VotRiskWarningStabilizer *stabilizer, int track_id) {
    size_t i;
    for (i = 0; i < VOT_MAX_TRACKS; i++) {
        if (stabilizer->entries[i].active && stabilizer->entries[i].track_id == track_id) {
            stabilizer->entries[i].active = false;
            stabilizer->entries[i].count = 0;
            return;
        }
    }
}

VotRiskAssessment vot_risk_warning_stabilize_one(VotRiskWarningStabilizer *stabilizer, VotRiskAssessment assessment) {
    VotRiskAssessment stabilized = assessment;
    int *count;
    if (assessment.level <= VOT_RISK_SAFE) {
        vot_warning_remove_track(stabilizer, assessment.track_id);
        return assessment;
    }
    count = vot_warning_count_for_track(stabilizer, assessment.track_id, true);
    (*count)++;
    if (*count < stabilizer->min_warning_frames) {
        stabilized.score = 0.0;
        stabilized.level = VOT_RISK_SAFE;
    }
    return stabilized;
}

VotRuntimeOptions vot_runtime_options_default(void) {
    VotRuntimeOptions options;
    memset(&options, 0, sizeof(options));
    vot_copy_class_name(options.source, sizeof(options.source), "camera");
    options.camera_index = 1;
    vot_copy_class_name(options.camera_backend, sizeof(options.camera_backend), "ffmpeg");
    vot_copy_class_name(options.camera_name, sizeof(options.camera_name), "USB Camera");
    vot_copy_class_name(options.runtime_profile, sizeof(options.runtime_profile), "balanced");
    options.width = 1280;
    options.height = 720;
    options.fps = 30.0;
    vot_copy_class_name(options.model, sizeof(options.model), "yolo11n.pt");
    vot_copy_class_name(options.tracker, sizeof(options.tracker), "vehicle_botsort.yaml");
    options.conf = 0.02;
    options.imgsz = 1024;
    options.max_det = 50;
    options.export_openvino = false;
    vot_copy_class_name(options.target_classes, sizeof(options.target_classes), "car,bicycle,motorcycle,bus,truck");
    options.device[0] = '\0';
    options.camera_height = 1.2;
    options.camera_pitch = 5.0;
    options.fov = 120.0;
    vot_copy_class_name(options.fov_type, sizeof(options.fov_type), "diagonal");
    options.has_horizontal_fov = false;
    vot_copy_class_name(options.distance_mode, sizeof(options.distance_mode), "fused");
    options.size_weight = 0.75;
    options.distance_scale = 1.0;
    options.speed_scale = 1.0;
    options.speed_window = 1.5;
    options.distance_smoothing = 0.35;
    options.max_speed = 40.0;
    vot_copy_class_name(options.enhance, sizeof(options.enhance), "off");
    options.display_scale = 1.0;
    options.max_frames = 0;
    options.no_display = false;
    options.video_every_frame = false;
    return options;
}

bool vot_runtime_options_set_profile(VotRuntimeOptions *options, const char *profile) {
    if (strcmp(profile, "realtime") == 0) {
        vot_copy_class_name(options->runtime_profile, sizeof(options->runtime_profile), "realtime");
        options->width = 960;
        options->height = 540;
        options->imgsz = 512;
        options->conf = 0.03;
        options->max_det = 50;
        return true;
    }
    if (strcmp(profile, "balanced") == 0) {
        vot_copy_class_name(options->runtime_profile, sizeof(options->runtime_profile), "balanced");
        options->width = 1280;
        options->height = 720;
        options->imgsz = 1024;
        options->conf = 0.02;
        options->max_det = 50;
        return true;
    }
    if (strcmp(profile, "quality") == 0) {
        vot_copy_class_name(options->runtime_profile, sizeof(options->runtime_profile), "quality");
        options->width = 1920;
        options->height = 1080;
        options->imgsz = 1024;
        options->conf = 0.02;
        options->max_det = 50;
        return true;
    }
    return false;
}

static bool vot_require_value(int *index, int argc, char **argv, const char *option, const char **value, char *error, size_t error_size) {
    if (*index + 1 >= argc) {
        snprintf(error, error_size, "Missing value for %s", option);
        return false;
    }
    (*index)++;
    *value = argv[*index];
    return true;
}

bool vot_runtime_options_parse(VotRuntimeOptions *options, int argc, char **argv, char *error, size_t error_size) {
    int i;
    bool width_overridden = false;
    bool height_overridden = false;
    bool imgsz_overridden = false;
    bool conf_overridden = false;
    bool max_det_overridden = false;
    *options = vot_runtime_options_default();
    if (error_size > 0) {
        error[0] = '\0';
    }

    for (i = 1; i < argc; i++) {
        const char *value = NULL;
        if (strcmp(argv[i], "--source") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            vot_copy_class_name(options->source, sizeof(options->source), value);
        } else if (strcmp(argv[i], "--video") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            vot_copy_class_name(options->video, sizeof(options->video), value);
        } else if (strcmp(argv[i], "--camera-index") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            options->camera_index = atoi(value);
        } else if (strcmp(argv[i], "--camera-backend") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            vot_copy_class_name(options->camera_backend, sizeof(options->camera_backend), value);
        } else if (strcmp(argv[i], "--camera-name") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            vot_copy_class_name(options->camera_name, sizeof(options->camera_name), value);
        } else if (strcmp(argv[i], "--runtime-profile") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            vot_copy_class_name(options->runtime_profile, sizeof(options->runtime_profile), value);
        } else if (strcmp(argv[i], "--width") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            options->width = atoi(value);
            width_overridden = true;
        } else if (strcmp(argv[i], "--height") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            options->height = atoi(value);
            height_overridden = true;
        } else if (strcmp(argv[i], "--fps") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            options->fps = atof(value);
        } else if (strcmp(argv[i], "--model") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            vot_copy_class_name(options->model, sizeof(options->model), value);
        } else if (strcmp(argv[i], "--tracker") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            vot_copy_class_name(options->tracker, sizeof(options->tracker), value);
        } else if (strcmp(argv[i], "--conf") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            options->conf = atof(value);
            conf_overridden = true;
        } else if (strcmp(argv[i], "--imgsz") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            options->imgsz = atoi(value);
            imgsz_overridden = true;
        } else if (strcmp(argv[i], "--max-det") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            options->max_det = atoi(value);
            max_det_overridden = true;
        } else if (strcmp(argv[i], "--export-openvino") == 0) {
            options->export_openvino = true;
        } else if (strcmp(argv[i], "--target-classes") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            vot_copy_class_name(options->target_classes, sizeof(options->target_classes), value);
        } else if (strcmp(argv[i], "--device") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            vot_copy_class_name(options->device, sizeof(options->device), value);
        } else if (strcmp(argv[i], "--camera-height") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            options->camera_height = atof(value);
        } else if (strcmp(argv[i], "--camera-pitch") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            options->camera_pitch = atof(value);
        } else if (strcmp(argv[i], "--fov") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            options->fov = atof(value);
        } else if (strcmp(argv[i], "--fov-type") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            vot_copy_class_name(options->fov_type, sizeof(options->fov_type), value);
        } else if (strcmp(argv[i], "--horizontal-fov") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            options->has_horizontal_fov = true;
            options->horizontal_fov = atof(value);
        } else if (strcmp(argv[i], "--distance-mode") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            vot_copy_class_name(options->distance_mode, sizeof(options->distance_mode), value);
        } else if (strcmp(argv[i], "--size-weight") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            options->size_weight = atof(value);
        } else if (strcmp(argv[i], "--distance-scale") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            options->distance_scale = atof(value);
        } else if (strcmp(argv[i], "--speed-scale") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            options->speed_scale = atof(value);
        } else if (strcmp(argv[i], "--speed-window") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            options->speed_window = atof(value);
        } else if (strcmp(argv[i], "--distance-smoothing") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            options->distance_smoothing = atof(value);
        } else if (strcmp(argv[i], "--max-speed") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            options->max_speed = atof(value);
        } else if (strcmp(argv[i], "--enhance") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            vot_copy_class_name(options->enhance, sizeof(options->enhance), value);
        } else if (strcmp(argv[i], "--display-scale") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            options->display_scale = atof(value);
        } else if (strcmp(argv[i], "--save-output") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            vot_copy_class_name(options->save_output, sizeof(options->save_output), value);
        } else if (strcmp(argv[i], "--max-frames") == 0) {
            if (!vot_require_value(&i, argc, argv, argv[i], &value, error, error_size)) return false;
            options->max_frames = atoi(value);
        } else if (strcmp(argv[i], "--no-display") == 0) {
            options->no_display = true;
        } else if (strcmp(argv[i], "--video-every-frame") == 0) {
            options->video_every_frame = true;
        } else {
            snprintf(error, error_size, "Unknown option: %s", argv[i]);
            return false;
        }
    }

    {
        VotRuntimeOptions profile_values = *options;
        if (!vot_runtime_options_set_profile(&profile_values, options->runtime_profile)) {
            snprintf(error, error_size, "Unknown runtime profile: %s", options->runtime_profile);
            return false;
        }
        if (!width_overridden) {
            options->width = profile_values.width;
        }
        if (!height_overridden) {
            options->height = profile_values.height;
        }
        if (!imgsz_overridden) {
            options->imgsz = profile_values.imgsz;
        }
        if (!conf_overridden) {
            options->conf = profile_values.conf;
        }
        if (!max_det_overridden) {
            options->max_det = profile_values.max_det;
        }
    }
    return true;
}

bool vot_video_should_skip_frames(const VotRuntimeOptions *options) {
    return strcmp(options->source, "video") == 0 && !options->video_every_frame && !options->no_display;
}

int vot_display_wait_ms(const VotRuntimeOptions *options, double capture_fps) {
    (void)options;
    (void)capture_fps;
    return 1;
}

void vot_mjpeg_parser_init(VotMjpegFrameParser *parser) {
    memset(parser, 0, sizeof(*parser));
}

void vot_mjpeg_parser_destroy(VotMjpegFrameParser *parser) {
    free(parser->buffer);
    parser->buffer = NULL;
    parser->length = 0;
    parser->capacity = 0;
}

static bool vot_mjpeg_parser_reserve(VotMjpegFrameParser *parser, size_t needed) {
    unsigned char *new_buffer;
    size_t new_capacity = parser->capacity == 0 ? 65536 : parser->capacity;
    while (new_capacity < needed) {
        new_capacity *= 2;
        if (new_capacity > VOT_MJPEG_BUFFER_CAPACITY) {
            return false;
        }
    }
    if (new_capacity == parser->capacity) {
        return true;
    }
    new_buffer = (unsigned char *)realloc(parser->buffer, new_capacity);
    if (new_buffer == NULL) {
        return false;
    }
    parser->buffer = new_buffer;
    parser->capacity = new_capacity;
    return true;
}

static size_t vot_find_marker(const unsigned char *data, size_t length, unsigned char a, unsigned char b, size_t start) {
    size_t i;
    if (length < 2 || start >= length - 1) {
        return (size_t)-1;
    }
    for (i = start; i + 1 < length; i++) {
        if (data[i] == a && data[i + 1] == b) {
            return i;
        }
    }
    return (size_t)-1;
}

size_t vot_mjpeg_parser_feed(VotMjpegFrameParser *parser, const unsigned char *chunk, size_t chunk_length, VotByteSpan *out_frames, size_t out_capacity) {
    size_t frame_count = 0;
    if (chunk_length > 0) {
        if (!vot_mjpeg_parser_reserve(parser, parser->length + chunk_length)) {
            parser->length = 0;
            return 0;
        }
        memcpy(parser->buffer + parser->length, chunk, chunk_length);
        parser->length += chunk_length;
    }

    while (frame_count < out_capacity) {
        size_t start = vot_find_marker(parser->buffer, parser->length, 0xff, 0xd8, 0);
        size_t end;
        size_t frame_length;
        unsigned char *frame_copy;
        if (start == (size_t)-1) {
            parser->length = 0;
            break;
        }
        if (start > 0) {
            memmove(parser->buffer, parser->buffer + start, parser->length - start);
            parser->length -= start;
            start = 0;
        }
        end = vot_find_marker(parser->buffer, parser->length, 0xff, 0xd9, 2);
        if (end == (size_t)-1) {
            break;
        }
        frame_length = end + 2;
        frame_copy = (unsigned char *)malloc(frame_length);
        if (frame_copy == NULL) {
            break;
        }
        memcpy(frame_copy, parser->buffer, frame_length);
        out_frames[frame_count].data = frame_copy;
        out_frames[frame_count].length = frame_length;
        frame_count++;
        memmove(parser->buffer, parser->buffer + frame_length, parser->length - frame_length);
        parser->length -= frame_length;
    }
    return frame_count;
}

void vot_mjpeg_parser_free_frames(VotByteSpan *frames, size_t frame_count) {
    size_t i;
    for (i = 0; i < frame_count; i++) {
        free(frames[i].data);
        frames[i].data = NULL;
        frames[i].length = 0;
    }
}
