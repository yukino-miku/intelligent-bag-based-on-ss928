#include "vot.h"
#include "vot_backend.h"

#include <onnxruntime_cxx_api.h>
#include <opencv2/opencv.hpp>
#include <opencv2/core/utils/logger.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace fs = std::filesystem;

namespace {

constexpr const char *kWindowName = "YOLO Tracking Distance Speed";
constexpr float kNmsIouThreshold = 0.45f;

bool has_flag(int argc, char **argv, const char *flag) {
    for (int i = 1; i < argc; i++) {
        if (std::strcmp(argv[i], flag) == 0) {
            return true;
        }
    }
    return false;
}

std::string as_string(const char *value) {
    return value == nullptr ? std::string() : std::string(value);
}

bool file_exists(const fs::path &path) {
    std::error_code error;
    return fs::exists(path, error) && fs::is_regular_file(path, error);
}

fs::path current_or_parent_path(const char *path_text) {
    fs::path path(path_text);
    if (file_exists(path)) {
        return path;
    }
    fs::path parent_path = fs::path("..") / path;
    if (file_exists(parent_path)) {
        return parent_path;
    }
    return path;
}

fs::path resolve_onnx_model_path(const VotRuntimeOptions &options) {
    fs::path model_path = current_or_parent_path(options.model);
    if (model_path.extension() == ".onnx" && file_exists(model_path)) {
        return model_path;
    }

    fs::path stem = model_path.stem();
    std::vector<fs::path> candidates = {
        fs::path("models") / (stem.string() + "_imgsz" + std::to_string(options.imgsz) + ".onnx"),
        fs::path("..") / "models" / (stem.string() + "_imgsz" + std::to_string(options.imgsz) + ".onnx"),
        fs::path("..") / "c_port" / "models" / (stem.string() + "_imgsz" + std::to_string(options.imgsz) + ".onnx"),
        fs::path("models") / (stem.string() + ".onnx"),
        fs::path("..") / (stem.string() + ".onnx"),
    };
    for (const fs::path &candidate : candidates) {
        if (file_exists(candidate)) {
            return candidate;
        }
    }

    throw std::runtime_error(
        "ONNX model for requested --imgsz not found. Export first:\n"
        "  powershell -ExecutionPolicy Bypass -File .\\export_yolo_onnx.ps1"
    );
}

void print_usage(const char *program) {
    std::printf("Usage:\n");
    std::printf("  %s --source camera [options]\n", program);
    std::printf("  %s --source video --video PATH [options]\n", program);
    std::printf("  %s --print-config [options]\n", program);
    std::printf("  %s --backend-status\n", program);
    std::printf("\n");
    std::printf("This MSVC/OpenCV/ONNX Runtime build runs the C core with a live/video backend.\n");
}

void print_config(const VotRuntimeOptions &options) {
    std::printf("source=%s\n", options.source);
    std::printf("video=%s\n", options.video);
    std::printf("camera_index=%d\n", options.camera_index);
    std::printf("camera_backend=%s\n", options.camera_backend);
    std::printf("camera_name=%s\n", options.camera_name);
    std::printf("runtime_profile=%s\n", options.runtime_profile);
    std::printf("width=%d\n", options.width);
    std::printf("height=%d\n", options.height);
    std::printf("fps=%.3f\n", options.fps);
    std::printf("model=%s\n", options.model);
    std::printf("tracker=%s\n", options.tracker);
    std::printf("conf=%.6f\n", options.conf);
    std::printf("imgsz=%d\n", options.imgsz);
    std::printf("max_det=%d\n", options.max_det);
    std::printf("target_classes=%s\n", options.target_classes);
    std::printf("device=%s\n", options.device);
    std::printf("camera_height=%.6f\n", options.camera_height);
    std::printf("camera_pitch=%.6f\n", options.camera_pitch);
    std::printf("fov=%.6f\n", options.fov);
    std::printf("fov_type=%s\n", options.fov_type);
    if (options.has_horizontal_fov) {
        std::printf("horizontal_fov=%.6f\n", options.horizontal_fov);
    }
    std::printf("distance_mode=%s\n", options.distance_mode);
    std::printf("size_weight=%.6f\n", options.size_weight);
    std::printf("distance_scale=%.6f\n", options.distance_scale);
    std::printf("speed_scale=%.6f\n", options.speed_scale);
    std::printf("speed_window=%.6f\n", options.speed_window);
    std::printf("distance_smoothing=%.6f\n", options.distance_smoothing);
    std::printf("max_speed=%.6f\n", options.max_speed);
    std::printf("enhance=%s\n", options.enhance);
    std::printf("display_scale=%.6f\n", options.display_scale);
    std::printf("save_output=%s\n", options.save_output);
    std::printf("max_frames=%d\n", options.max_frames);
    std::printf("no_display=%s\n", options.no_display ? "true" : "false");
    std::printf("video_every_frame=%s\n", options.video_every_frame ? "true" : "false");
}

void print_backend_status(void) {
    const fs::path ort_root = "third_party/onnxruntime/onnxruntime-win-x64-1.26.0";
    const fs::path opencv_root = "third_party/opencv";
    const fs::path vcvars = "C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/VC/Auxiliary/Build/vcvars64.bat";
    const std::vector<std::pair<std::string, fs::path>> probes = {
        {"ONNX Runtime header", ort_root / "include/onnxruntime_cxx_api.h"},
        {"ONNX Runtime DLL", ort_root / "lib/onnxruntime.dll"},
        {"ONNX Runtime lib", ort_root / "lib/onnxruntime.lib"},
        {"OpenCV header", opencv_root / "build/include/opencv2/opencv.hpp"},
        {"OpenCV DLL", opencv_root / "build/x64/vc16/bin/opencv_world4130.dll"},
        {"OpenCV lib", opencv_root / "build/x64/vc16/lib/opencv_world4130.lib"},
        {"MSVC vcvars64", vcvars},
    };

    std::printf("Live backend status:\n");
    for (const auto &probe : probes) {
        std::printf("  [%s] %s: %s\n", file_exists(probe.second) ? "ok" : "missing", probe.first.c_str(), probe.second.string().c_str());
    }
}

int filtered_argc_without_flag(int argc, char **argv, const char *flag, std::vector<char *> &filtered) {
    filtered.clear();
    filtered.push_back(argv[0]);
    for (int i = 1; i < argc; i++) {
        if (std::strcmp(argv[i], flag) != 0) {
            filtered.push_back(argv[i]);
        }
    }
    return static_cast<int>(filtered.size());
}

cv::Mat enhance_frame_for_detection(const cv::Mat &frame, const std::string &mode) {
    if (mode == "off") {
        return frame;
    }

    cv::Mat gray;
    cv::cvtColor(frame, gray, cv::COLOR_BGR2GRAY);
    if (mode == "auto" && cv::mean(gray)[0] >= 75.0) {
        return frame;
    }

    cv::Mat lab;
    cv::cvtColor(frame, lab, cv::COLOR_BGR2Lab);
    std::vector<cv::Mat> channels;
    cv::split(lab, channels);
    cv::Ptr<cv::CLAHE> clahe = cv::createCLAHE(2.0, cv::Size(8, 8));
    clahe->apply(channels[0], channels[0]);
    cv::merge(channels, lab);

    cv::Mat enhanced;
    cv::cvtColor(lab, enhanced, cv::COLOR_Lab2BGR);
    return enhanced;
}

struct LetterboxResult {
    cv::Mat image;
    double scale = 1.0;
    double pad_x = 0.0;
    double pad_y = 0.0;
};

LetterboxResult letterbox(const cv::Mat &frame, int input_width, int input_height) {
    LetterboxResult result;
    result.scale = std::min(static_cast<double>(input_width) / frame.cols, static_cast<double>(input_height) / frame.rows);
    const int resized_width = static_cast<int>(std::round(frame.cols * result.scale));
    const int resized_height = static_cast<int>(std::round(frame.rows * result.scale));
    result.pad_x = (input_width - resized_width) / 2.0;
    result.pad_y = (input_height - resized_height) / 2.0;

    cv::Mat resized;
    cv::resize(frame, resized, cv::Size(resized_width, resized_height), 0.0, 0.0, cv::INTER_LINEAR);
    result.image = cv::Mat(input_height, input_width, frame.type(), cv::Scalar(114, 114, 114));
    resized.copyTo(result.image(cv::Rect(static_cast<int>(std::floor(result.pad_x)), static_cast<int>(std::floor(result.pad_y)), resized_width, resized_height)));
    return result;
}

std::vector<float> bgr_to_rgb_chw_float(const cv::Mat &bgr) {
    cv::Mat rgb;
    cv::cvtColor(bgr, rgb, cv::COLOR_BGR2RGB);
    cv::Mat float_image;
    rgb.convertTo(float_image, CV_32F, 1.0 / 255.0);

    std::vector<float> tensor(static_cast<size_t>(3 * float_image.rows * float_image.cols));
    const int plane_size = float_image.rows * float_image.cols;
    for (int y = 0; y < float_image.rows; y++) {
        const cv::Vec3f *row = float_image.ptr<cv::Vec3f>(y);
        for (int x = 0; x < float_image.cols; x++) {
            const int index = y * float_image.cols + x;
            tensor[static_cast<size_t>(index)] = row[x][0];
            tensor[static_cast<size_t>(plane_size + index)] = row[x][1];
            tensor[static_cast<size_t>(plane_size * 2 + index)] = row[x][2];
        }
    }
    return tensor;
}

double clamp_double(double value, double low, double high) {
    return std::max(low, std::min(high, value));
}

class YoloOnnxDetector {
public:
    explicit YoloOnnxDetector(const fs::path &model_path)
        : env_(ORT_LOGGING_LEVEL_WARNING, "vision_obstacle_tracker_c"),
          session_options_(),
          session_(nullptr) {
        session_options_.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
        session_options_.SetIntraOpNumThreads(1);
        session_ = std::make_unique<Ort::Session>(env_, model_path.wstring().c_str(), session_options_);

        Ort::AllocatorWithDefaultOptions allocator;
        input_name_ = session_->GetInputNameAllocated(0, allocator).get();
        output_name_ = session_->GetOutputNameAllocated(0, allocator).get();

        std::vector<int64_t> input_shape = session_->GetInputTypeInfo(0).GetTensorTypeAndShapeInfo().GetShape();
        if (input_shape.size() != 4 || input_shape[0] != 1 || input_shape[1] != 3) {
            throw std::runtime_error("Only static NCHW YOLO ONNX models with shape [1,3,H,W] are supported.");
        }
        input_height_ = static_cast<int>(input_shape[2]);
        input_width_ = static_cast<int>(input_shape[3]);
        if (input_height_ <= 0 || input_width_ <= 0) {
            throw std::runtime_error("Dynamic ONNX input shapes are not supported by this build.");
        }
    }

    int input_width() const { return input_width_; }
    int input_height() const { return input_height_; }

    std::vector<BackendDetection> detect(
        const cv::Mat &frame,
        const BackendTargetClassFilter &target_filter,
        float conf_threshold,
        int max_det
    ) {
        LetterboxResult prep = letterbox(frame, input_width_, input_height_);
        std::vector<float> input_tensor = bgr_to_rgb_chw_float(prep.image);
        std::array<int64_t, 4> input_shape = {1, 3, input_height_, input_width_};
        Ort::MemoryInfo memory_info = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
        Ort::Value input = Ort::Value::CreateTensor<float>(
            memory_info,
            input_tensor.data(),
            input_tensor.size(),
            input_shape.data(),
            input_shape.size()
        );

        const char *input_names[] = {input_name_.c_str()};
        const char *output_names[] = {output_name_.c_str()};
        std::vector<Ort::Value> outputs = session_->Run(
            Ort::RunOptions{nullptr},
            input_names,
            &input,
            1,
            output_names,
            1
        );

        return decode(outputs[0], frame.cols, frame.rows, prep, target_filter, conf_threshold, max_det);
    }

private:
    std::vector<BackendDetection> decode(
        Ort::Value &output,
        int frame_width,
        int frame_height,
        const LetterboxResult &prep,
        const BackendTargetClassFilter &target_filter,
        float conf_threshold,
        int max_det
    ) {
        std::vector<int64_t> shape = output.GetTensorTypeAndShapeInfo().GetShape();
        if (shape.size() != 3 || shape[0] != 1) {
            throw std::runtime_error("Unexpected YOLO output shape.");
        }

        const float *data = output.GetTensorData<float>();
        const bool channel_first = shape[1] == 84;
        const int channels = channel_first ? static_cast<int>(shape[1]) : static_cast<int>(shape[2]);
        const int anchors = channel_first ? static_cast<int>(shape[2]) : static_cast<int>(shape[1]);
        if (channels < 5) {
            throw std::runtime_error("Unexpected YOLO output channel count.");
        }

        auto value_at = [data, channel_first, anchors, channels](int anchor, int channel) -> float {
            if (channel_first) {
                return data[static_cast<size_t>(channel * anchors + anchor)];
            }
            return data[static_cast<size_t>(anchor * channels + channel)];
        };

        std::vector<BackendDetection> detections;
        detections.reserve(static_cast<size_t>(std::min(anchors, 1024)));
        for (int anchor = 0; anchor < anchors; anchor++) {
            int best_class = -1;
            float best_score = 0.0f;
            for (int class_offset = 4; class_offset < channels; class_offset++) {
                const int class_id = class_offset - 4;
                if (!backend_should_keep_class(target_filter, class_id)) {
                    continue;
                }
                const float score = value_at(anchor, class_offset);
                if (score > best_score) {
                    best_score = score;
                    best_class = class_id;
                }
            }

            if (best_class < 0 || best_score < conf_threshold) {
                continue;
            }

            const double cx = value_at(anchor, 0);
            const double cy = value_at(anchor, 1);
            const double w = value_at(anchor, 2);
            const double h = value_at(anchor, 3);
            BackendDetection detection;
            detection.x1 = clamp_double((cx - w / 2.0 - prep.pad_x) / prep.scale, 0.0, static_cast<double>(frame_width - 1));
            detection.y1 = clamp_double((cy - h / 2.0 - prep.pad_y) / prep.scale, 0.0, static_cast<double>(frame_height - 1));
            detection.x2 = clamp_double((cx + w / 2.0 - prep.pad_x) / prep.scale, 0.0, static_cast<double>(frame_width - 1));
            detection.y2 = clamp_double((cy + h / 2.0 - prep.pad_y) / prep.scale, 0.0, static_cast<double>(frame_height - 1));
            detection.class_id = best_class;
            detection.score = best_score;
            if (detection.x2 > detection.x1 && detection.y2 > detection.y1) {
                detections.push_back(detection);
            }
        }

        return backend_nms(detections, kNmsIouThreshold, max_det);
    }

    Ort::Env env_;
    Ort::SessionOptions session_options_;
    std::unique_ptr<Ort::Session> session_;
    std::string input_name_;
    std::string output_name_;
    int input_width_ = 0;
    int input_height_ = 0;
};

cv::VideoCapture open_capture(const VotRuntimeOptions &options) {
    cv::VideoCapture capture;
    if (std::strcmp(options.source, "video") == 0) {
        if (std::strlen(options.video) == 0) {
            throw std::runtime_error("Specify --video PATH when using --source video.");
        }
        capture.open(options.video);
        if (!capture.isOpened()) {
            throw std::runtime_error("Could not open video: " + as_string(options.video));
        }
        return capture;
    }

    capture.open(options.camera_index);
    if (!capture.isOpened() && options.camera_index != 0) {
        std::cerr << "Camera index " << options.camera_index << " failed; trying camera index 0.\n";
        capture.open(0);
    }
    if (!capture.isOpened()) {
        throw std::runtime_error("Could not open camera. Try --camera-index 0 or 1.");
    }

    capture.set(cv::CAP_PROP_FOURCC, cv::VideoWriter::fourcc('M', 'J', 'P', 'G'));
    capture.set(cv::CAP_PROP_FRAME_WIDTH, options.width);
    capture.set(cv::CAP_PROP_FRAME_HEIGHT, options.height);
    capture.set(cv::CAP_PROP_FPS, options.fps);
    return capture;
}

cv::VideoWriter create_writer(const VotRuntimeOptions &options, const cv::Size &frame_size, double fps) {
    cv::VideoWriter writer;
    if (std::strlen(options.save_output) == 0) {
        return writer;
    }

    fs::path output_path(options.save_output);
    if (output_path.has_parent_path()) {
        std::error_code error;
        fs::create_directories(output_path.parent_path(), error);
    }
    writer.open(options.save_output, cv::VideoWriter::fourcc('m', 'p', '4', 'v'), std::max(1.0, fps), frame_size);
    if (!writer.isOpened()) {
        throw std::runtime_error("Could not open output writer: " + as_string(options.save_output));
    }
    return writer;
}

VotCameraCalibration make_calibration(const VotRuntimeOptions &options, const cv::Mat &frame) {
    VotCameraCalibration calibration = vot_camera_calibration_default();
    calibration.image_width = frame.cols;
    calibration.image_height = frame.rows;
    calibration.fov_deg = options.fov;
    vot_copy_class_name(calibration.fov_type, sizeof(calibration.fov_type), options.fov_type);
    calibration.has_horizontal_fov = options.has_horizontal_fov;
    calibration.horizontal_fov_deg = options.horizontal_fov;
    calibration.camera_height_m = options.camera_height;
    calibration.camera_pitch_deg = options.camera_pitch;
    calibration.distance_scale = options.distance_scale;
    return calibration;
}

VotDetectionObservation detection_to_observation(
    const BackendDetection &detection,
    const VotCameraCalibration &calibration,
    const VotRuntimeOptions &options,
    double timestamp_s
) {
    VotDetectionObservation observation;
    std::memset(&observation, 0, sizeof(observation));
    observation.track_id = detection.track_id;
    vot_copy_class_name(observation.class_name, sizeof(observation.class_name), backend_coco_class_name(detection.class_id));
    observation.confidence = detection.score;
    observation.bbox = {detection.x1, detection.y1, detection.x2, detection.y2};
    observation.timestamp_s = timestamp_s;

    VotDistanceEstimate estimate;
    if (vot_estimate_ground_point_from_bbox(observation.bbox, observation.class_name, &calibration, options.distance_mode, options.size_weight, &estimate)) {
        observation.has_ground_point = true;
        observation.ground_point = estimate.point;
        vot_copy_class_name(observation.distance_source, sizeof(observation.distance_source), estimate.source);
    } else {
        observation.has_ground_point = false;
        vot_copy_class_name(observation.distance_source, sizeof(observation.distance_source), "unknown");
    }
    return observation;
}

std::string format_risk_suffix(const VotRiskAssessment &assessment);

std::string format_tracking_line(const VotTrackedObject &target) {
    std::ostringstream stream;
    stream << std::fixed << std::setprecision(1);
    stream << "ID " << target.track_id << " " << target.class_name << " ";
    stream << std::setprecision(2) << target.confidence << " ";
    stream << std::setprecision(1);
    if (target.has_distance) {
        stream << "d=" << target.distance_m << "m";
    } else {
        stream << "d=unknown";
    }
    stream << "(" << target.distance_source << ") ";
    stream << "v=" << target.speed_mps << "m/s";
    return stream.str();
}

std::string format_velocity_risk_line(const VotTrackedObject &target, const VotRiskAssessment &assessment) {
    std::ostringstream stream;
    stream << std::fixed << std::setprecision(1);
    stream << "vx=" << std::showpos << target.vx_mps << " ";
    stream << "vz=" << target.vz_mps << std::noshowpos << " ";
    stream << vot_risk_level_name(assessment.level);
    stream << std::setprecision(2) << " RS=" << assessment.score;
    if (assessment.has_ttc) {
        stream << std::setprecision(1) << " TTC=" << assessment.ttc_s << "s";
    }
    if (assessment.has_trajectory_distance) {
        stream << std::setprecision(1) << " T=" << assessment.trajectory_distance_m << "m";
    }
    return stream.str();
}

std::string format_risk_suffix(const VotRiskAssessment &assessment) {
    std::ostringstream stream;
    stream << std::fixed << std::setprecision(2);
    stream << "RiskScore=" << assessment.score << " " << vot_risk_level_name(assessment.level);
    if (assessment.has_ttc) {
        stream << std::setprecision(1) << " TTC=" << assessment.ttc_s << "s";
    }
    if (assessment.has_trajectory_distance) {
        stream << std::setprecision(1) << " TRAJ=" << assessment.trajectory_distance_m << "m";
    }
    return stream.str();
}

cv::Scalar color_for_risk(const VotRiskAssessment &assessment) {
    VotBgr bgr = vot_risk_color_bgr(assessment.level);
    return cv::Scalar(bgr.b, bgr.g, bgr.r);
}

void draw_text_line(cv::Mat &frame, const std::string &text, int x, int y, double scale, const cv::Scalar &color) {
    constexpr int thickness = 2;
    int baseline = 0;
    cv::Size text_size = cv::getTextSize(text, cv::FONT_HERSHEY_SIMPLEX, scale, thickness, &baseline);
    x = std::max(0, std::min(x, std::max(0, frame.cols - text_size.width - 4)));
    y = std::max(text_size.height + 4, std::min(y, std::max(text_size.height + 4, frame.rows - baseline - 4)));
    cv::Rect background(
        std::max(0, x - 2),
        std::max(0, y - text_size.height - 4),
        std::min(frame.cols - std::max(0, x - 2), text_size.width + 4),
        std::min(frame.rows - std::max(0, y - text_size.height - 4), text_size.height + baseline + 6)
    );
    if (background.area() > 0) {
        cv::Mat roi = frame(background);
        cv::Mat overlay(roi.size(), roi.type(), cv::Scalar(0, 0, 0));
        cv::addWeighted(overlay, 0.35, roi, 0.65, 0.0, roi);
    }
    cv::putText(frame, text, cv::Point(x, y), cv::FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv::LINE_AA);
}

void draw_overlay(
    cv::Mat &frame,
    const std::vector<VotTrackedObject> &tracked_objects,
    const std::vector<VotRiskAssessment> &risks,
    const std::string &fps_text,
    const std::string &source_text
) {
    for (const VotTrackedObject &target : tracked_objects) {
        auto risk_it = std::find_if(risks.begin(), risks.end(), [&target](const VotRiskAssessment &risk) {
            return risk.track_id == target.track_id;
        });
        VotRiskAssessment safe_risk{};
        safe_risk.track_id = target.track_id;
        safe_risk.level = VOT_RISK_SAFE;
        safe_risk.score = 0.0;
        const VotRiskAssessment &risk = risk_it == risks.end() ? safe_risk : *risk_it;
        const cv::Scalar color = color_for_risk(risk);
        const int thickness = risk.level >= VOT_RISK_DANGER ? 3 : 2;

        cv::Rect rect(
            static_cast<int>(std::round(target.bbox.x1)),
            static_cast<int>(std::round(target.bbox.y1)),
            static_cast<int>(std::round(target.bbox.x2 - target.bbox.x1)),
            static_cast<int>(std::round(target.bbox.y2 - target.bbox.y1))
        );
        rect &= cv::Rect(0, 0, frame.cols, frame.rows);
        if (rect.area() > 0) {
            cv::rectangle(frame, rect, color, thickness);
        }

        if (target.has_ground_point) {
            cv::Point foot(
                static_cast<int>(std::round((target.bbox.x1 + target.bbox.x2) / 2.0)),
                static_cast<int>(std::round(target.bbox.y2))
            );
            cv::circle(frame, foot, 5, color, -1);
        }

        const int label_x = std::max(0, static_cast<int>(std::round(target.bbox.x1)));
        int label_y = std::max(24, static_cast<int>(std::round(target.bbox.y1)) - 8);
        if (label_y < 128) {
            label_y = static_cast<int>(std::round(target.bbox.y2)) + 22;
        }
        draw_text_line(frame, format_tracking_line(target), label_x, label_y, 0.55, color);
        draw_text_line(frame, format_velocity_risk_line(target, risk), label_x, label_y + 22, 0.55, color);
    }

    cv::putText(frame, source_text, cv::Point(24, 36), cv::FONT_HERSHEY_SIMPLEX, 0.9, cv::Scalar(255, 255, 255), 2, cv::LINE_AA);
    cv::putText(frame, fps_text, cv::Point(24, 72), cv::FONT_HERSHEY_SIMPLEX, 0.9, cv::Scalar(255, 255, 255), 2, cv::LINE_AA);
    cv::putText(frame, "q/Esc: exit  Space: pause", cv::Point(24, 108), cv::FONT_HERSHEY_SIMPLEX, 0.8, cv::Scalar(220, 220, 220), 2, cv::LINE_AA);
}

cv::Mat resize_for_display(const cv::Mat &frame, double scale) {
    if (scale <= 0.0 || std::abs(scale - 1.0) < 1e-6) {
        return frame;
    }
    cv::Mat resized;
    cv::resize(frame, resized, cv::Size(), scale, scale, cv::INTER_AREA);
    return resized;
}

double now_seconds() {
    using clock = std::chrono::steady_clock;
    static const clock::time_point start = clock::now();
    return std::chrono::duration<double>(clock::now() - start).count();
}

int run_live_backend(const VotRuntimeOptions &options) {
    fs::path model_path = resolve_onnx_model_path(options);
    std::cout << "Using ONNX model: " << model_path.string() << "\n";

    cv::VideoCapture capture = open_capture(options);
    double capture_fps = capture.get(cv::CAP_PROP_FPS);
    if (capture_fps <= 0.0 || !std::isfinite(capture_fps)) {
        capture_fps = options.fps > 0.0 ? options.fps : 30.0;
    }

    cv::Mat first_frame;
    if (!capture.read(first_frame) || first_frame.empty()) {
        throw std::runtime_error("Input opened but no frame could be read.");
    }

    VotCameraCalibration calibration = make_calibration(options, first_frame);
    cv::VideoWriter writer = create_writer(options, first_frame.size(), capture_fps);
    YoloOnnxDetector detector(model_path);
    if (detector.input_width() != options.imgsz || detector.input_height() != options.imgsz) {
        std::ostringstream message;
        message << "ONNX input size " << detector.input_width() << "x" << detector.input_height()
                << " does not match requested --imgsz " << options.imgsz
                << ". Export a matching model or change --imgsz.";
        throw std::runtime_error(message.str());
    }
    BackendTargetClassFilter target_filter = backend_parse_target_classes(options.target_classes);
    BackendSimpleTracker raw_tracker;
    VotStableTrackIdManager stable_ids;
    vot_stable_track_id_manager_init(&stable_ids, 2.0, 1.0);
    VotTrackState track_state;
    vot_track_state_init(&track_state, options.speed_window, options.distance_smoothing, options.max_speed, options.speed_scale);
    VotRiskModelConfig risk_config = vot_risk_model_config_default();
    VotRiskWarningStabilizer risk_stabilizer;
    vot_risk_warning_stabilizer_init(&risk_stabilizer, 3);

    if (!options.no_display) {
        cv::namedWindow(kWindowName, cv::WINDOW_NORMAL);
    }

    bool paused = false;
    int processed_frames = 0;
    int source_frame_index = 0;
    double last_loop = now_seconds();
    cv::Mat current_frame = first_frame;

    while (true) {
        if (options.max_frames > 0 && processed_frames >= options.max_frames) {
            break;
        }

        cv::Mat display_frame;
        if (!paused) {
            cv::Mat frame;
            if (processed_frames == 0) {
                frame = current_frame;
            } else if (!capture.read(frame) || frame.empty()) {
                break;
            }
            current_frame = frame;

            const double timestamp_s = std::strcmp(options.source, "video") == 0
                ? static_cast<double>(source_frame_index) / std::max(1.0, capture_fps)
                : now_seconds();

            cv::Mat inference_frame = enhance_frame_for_detection(frame, options.enhance);
            std::vector<BackendDetection> detections = detector.detect(
                inference_frame,
                target_filter,
                static_cast<float>(options.conf),
                options.max_det
            );
            detections = raw_tracker.update(detections);

            VotDetectionObservation raw_observations[VOT_MAX_OBSERVATIONS];
            const size_t raw_count = std::min(detections.size(), static_cast<size_t>(VOT_MAX_OBSERVATIONS));
            for (size_t i = 0; i < raw_count; i++) {
                raw_observations[i] = detection_to_observation(detections[i], calibration, options, timestamp_s);
            }

            VotDetectionObservation stable_observations[VOT_MAX_OBSERVATIONS];
            size_t stable_count = vot_stable_track_assign(&stable_ids, raw_observations, raw_count, stable_observations, VOT_MAX_OBSERVATIONS);

            std::vector<VotTrackedObject> tracked_objects;
            tracked_objects.reserve(stable_count);
            std::vector<VotRiskAssessment> risks;
            risks.reserve(stable_count);
            for (size_t i = 0; i < stable_count; i++) {
                VotTrackedObject tracked = vot_track_state_update(&track_state, stable_observations[i]);
                tracked_objects.push_back(tracked);
                VotRiskAssessment raw_risk = vot_assess_collision_risk(tracked, &risk_config);
                risks.push_back(vot_risk_warning_stabilize_one(&risk_stabilizer, raw_risk));
            }

            const double now = now_seconds();
            const double loop_dt = std::max(now - last_loop, 1e-6);
            last_loop = now;
            std::ostringstream fps_stream;
            fps_stream << std::fixed << std::setprecision(1) << "processing FPS: " << (1.0 / loop_dt);
            std::string source_text = std::string("source: ") + options.source;
            if (std::strcmp(options.source, "video") == 0 && std::strlen(options.video) > 0) {
                source_text += " " + fs::path(options.video).filename().string();
            }

            display_frame = frame.clone();
            draw_overlay(display_frame, tracked_objects, risks, fps_stream.str(), source_text);
            if (writer.isOpened()) {
                writer.write(display_frame);
            }

            processed_frames++;
            source_frame_index++;
        } else {
            display_frame = current_frame.clone();
            cv::putText(display_frame, "PAUSED", cv::Point(24, 36), cv::FONT_HERSHEY_SIMPLEX, 1.1, cv::Scalar(0, 220, 255), 2, cv::LINE_AA);
        }

        if (options.no_display) {
            continue;
        }

        cv::imshow(kWindowName, resize_for_display(display_frame, options.display_scale));
        const int key = cv::waitKey(vot_display_wait_ms(&options, capture_fps)) & 0xff;
        if (key == 27 || key == 'q') {
            break;
        }
        if (key == ' ') {
            paused = !paused;
        }
    }

    capture.release();
    if (writer.isOpened()) {
        writer.release();
    }
    if (!options.no_display) {
        cv::destroyAllWindows();
    }
    return 0;
}

}  // namespace

int main(int argc, char **argv) {
    try {
        cv::utils::logging::setLogLevel(cv::utils::logging::LOG_LEVEL_SILENT);

        if (argc == 1 || has_flag(argc, argv, "--help") || has_flag(argc, argv, "-h")) {
            print_usage(argv[0]);
            return 0;
        }

        if (has_flag(argc, argv, "--backend-status")) {
            print_backend_status();
            return 0;
        }

        std::vector<char *> filtered;
        int parsed_argc = argc;
        char **parsed_argv = argv;
        if (has_flag(argc, argv, "--print-config")) {
            parsed_argc = filtered_argc_without_flag(argc, argv, "--print-config", filtered);
            parsed_argv = filtered.data();
        }

        VotRuntimeOptions options;
        char error[256];
        if (!vot_runtime_options_parse(&options, parsed_argc, parsed_argv, error, sizeof(error))) {
            std::fprintf(stderr, "%s\n", error);
            return 2;
        }

        if (has_flag(argc, argv, "--print-config")) {
            print_config(options);
            return 0;
        }
        if (options.export_openvino) {
            std::fprintf(stderr, "--export-openvino is Python-only. Export ONNX and pass --model yolo11n.onnx for this C backend.\n");
            return 2;
        }
        return run_live_backend(options);
    } catch (const std::exception &exc) {
        std::fprintf(stderr, "error: %s\n", exc.what());
        return 2;
    }
}
