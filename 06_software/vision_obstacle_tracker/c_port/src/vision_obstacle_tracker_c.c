#include "vot.h"

#include <stdio.h>
#include <string.h>

static bool has_flag(int argc, char **argv, const char *flag) {
    int i;
    for (i = 1; i < argc; i++) {
        if (strcmp(argv[i], flag) == 0) {
            return true;
        }
    }
    return false;
}

static void print_usage(const char *program) {
    printf("Usage:\n");
    printf("  %s --print-config [same options as Python version]\n", program);
    printf("  %s --backend-status\n", program);
    printf("\n");
    printf("The C core mirrors the Python calibration, tracking, risk, runtime defaults,\n");
    printf("MJPEG parsing, and warning stabilization logic. Live YOLO/OpenCV video\n");
    printf("requires building an external backend against ONNX Runtime C API and OpenCV.\n");
}

static void print_config(const VotRuntimeOptions *options) {
    printf("source=%s\n", options->source);
    printf("video=%s\n", options->video);
    printf("camera_index=%d\n", options->camera_index);
    printf("camera_backend=%s\n", options->camera_backend);
    printf("camera_name=%s\n", options->camera_name);
    printf("runtime_profile=%s\n", options->runtime_profile);
    printf("width=%d\n", options->width);
    printf("height=%d\n", options->height);
    printf("fps=%.3f\n", options->fps);
    printf("model=%s\n", options->model);
    printf("tracker=%s\n", options->tracker);
    printf("conf=%.6f\n", options->conf);
    printf("imgsz=%d\n", options->imgsz);
    printf("max_det=%d\n", options->max_det);
    printf("export_openvino=%s\n", options->export_openvino ? "true" : "false");
    printf("target_classes=%s\n", options->target_classes);
    printf("device=%s\n", options->device);
    printf("camera_height=%.6f\n", options->camera_height);
    printf("camera_pitch=%.6f\n", options->camera_pitch);
    printf("fov=%.6f\n", options->fov);
    printf("fov_type=%s\n", options->fov_type);
    if (options->has_horizontal_fov) {
        printf("horizontal_fov=%.6f\n", options->horizontal_fov);
    }
    printf("distance_mode=%s\n", options->distance_mode);
    printf("size_weight=%.6f\n", options->size_weight);
    printf("distance_scale=%.6f\n", options->distance_scale);
    printf("speed_scale=%.6f\n", options->speed_scale);
    printf("speed_window=%.6f\n", options->speed_window);
    printf("distance_smoothing=%.6f\n", options->distance_smoothing);
    printf("max_speed=%.6f\n", options->max_speed);
    printf("enhance=%s\n", options->enhance);
    printf("display_scale=%.6f\n", options->display_scale);
    printf("save_output=%s\n", options->save_output);
    printf("max_frames=%d\n", options->max_frames);
    printf("no_display=%s\n", options->no_display ? "true" : "false");
    printf("video_every_frame=%s\n", options->video_every_frame ? "true" : "false");
}

typedef struct BackendProbeFile {
    const char *label;
    const char *path;
} BackendProbeFile;

static bool file_exists(const char *path) {
    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        return false;
    }
    fclose(file);
    return true;
}

static bool print_probe_group(const char *title, const BackendProbeFile *files, int count) {
    bool all_found = true;
    int i;

    printf("  %s:\n", title);
    for (i = 0; i < count; i++) {
        bool found = file_exists(files[i].path);
        printf("    [%s] %s: %s\n", found ? "ok" : "missing", files[i].label, files[i].path);
        if (!found) {
            all_found = false;
        }
    }
    return all_found;
}

static void print_backend_status(void) {
    static const BackendProbeFile onnx_files[] = {
        {"C API header", "third_party/onnxruntime/onnxruntime-win-x64-1.26.0/include/onnxruntime_c_api.h"},
        {"DLL", "third_party/onnxruntime/onnxruntime-win-x64-1.26.0/lib/onnxruntime.dll"},
        {"import library", "third_party/onnxruntime/onnxruntime-win-x64-1.26.0/lib/onnxruntime.lib"},
    };
    static const BackendProbeFile opencv_files[] = {
        {"C++ header", "third_party/opencv/build/include/opencv2/opencv.hpp"},
        {"world DLL", "third_party/opencv/build/x64/vc16/bin/opencv_world4130.dll"},
        {"world import library", "third_party/opencv/build/x64/vc16/lib/opencv_world4130.lib"},
    };
    static const BackendProbeFile msvc_files[] = {
        {"vcvars64", "C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/VC/Auxiliary/Build/vcvars64.bat"},
    };
    bool onnx_ok;
    bool opencv_ok;
    bool msvc_ok;

    printf("C core backend status:\n");
    printf("  calibration/risk/tracking/overlay/runtime: built in\n");
    onnx_ok = print_probe_group("ONNX Runtime 1.26.0", onnx_files, (int)(sizeof(onnx_files) / sizeof(onnx_files[0])));
    opencv_ok = print_probe_group("OpenCV 4.13.0 official Windows package", opencv_files, (int)(sizeof(opencv_files) / sizeof(opencv_files[0])));
    msvc_ok = print_probe_group("MSVC Build Tools", msvc_files, (int)(sizeof(msvc_files) / sizeof(msvc_files[0])));
    printf("\n");
    printf("Backend readiness summary:\n");
    printf("  YOLO ONNX inference files: %s\n", onnx_ok ? "ready" : "missing files");
    printf("  OpenCV video/drawing files: %s\n", opencv_ok ? "ready" : "missing files");
    printf("  MSVC toolchain for vc16 OpenCV libs: %s\n", msvc_ok ? "ready" : "missing files");
    printf("\n");
    printf("The dependency-free executable still only runs core logic and configuration\n");
    printf("validation. A live/video build must link a backend against these libraries.\n");
}

int main(int argc, char **argv) {
    VotRuntimeOptions options;
    char error[256];

    if (argc == 1 || has_flag(argc, argv, "--help") || has_flag(argc, argv, "-h")) {
        print_usage(argv[0]);
        return 0;
    }

    if (has_flag(argc, argv, "--backend-status")) {
        print_backend_status();
        return 0;
    }

    if (has_flag(argc, argv, "--print-config")) {
        int filtered_argc = 1;
        char *filtered_argv[128];
        int i;
        filtered_argv[0] = argv[0];
        for (i = 1; i < argc && filtered_argc < 128; i++) {
            if (strcmp(argv[i], "--print-config") != 0) {
                filtered_argv[filtered_argc++] = argv[i];
            }
        }
        if (!vot_runtime_options_parse(&options, filtered_argc, filtered_argv, error, sizeof(error))) {
            fprintf(stderr, "%s\n", error);
            return 2;
        }
        print_config(&options);
        return 0;
    }

    print_backend_status();
    fprintf(stderr, "No live video backend is compiled into this dependency-free build.\n");
    return 2;
}
