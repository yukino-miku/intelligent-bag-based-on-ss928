#include "frame_preprocess.h"
#include "ss928_acl_detector.h"
#include "vot_backend.h"
#include "yolov8_postprocess.h"

#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace {

struct Options {
    std::string model;
    std::string input;
    std::string target_classes = "car,bicycle,motorcycle,bus,truck";
    int source_width = 640;
    int source_height = 640;
    int repeat = 1;
    float confidence = 0.25f;
    float nms = 0.45f;
    int max_detections = 50;
};

bool parse_number(const char *text, int *value) {
    char *end = nullptr;
    const long parsed = std::strtol(text, &end, 10);
    if (end == text || *end != '\0') return false;
    *value = static_cast<int>(parsed);
    return true;
}

bool parse_number(const char *text, float *value) {
    char *end = nullptr;
    const float parsed = std::strtof(text, &end);
    if (end == text || *end != '\0') return false;
    *value = parsed;
    return true;
}

bool parse_options(int argc, char **argv, Options *options) {
    for (int index = 1; index < argc; ++index) {
        const std::string key = argv[index];
        if (index + 1 >= argc) return false;
        const char *value = argv[++index];
        if (key == "--model") options->model = value;
        else if (key == "--input") options->input = value;
        else if (key == "--source-width") { if (!parse_number(value, &options->source_width)) return false; }
        else if (key == "--source-height") { if (!parse_number(value, &options->source_height)) return false; }
        else if (key == "--repeat") { if (!parse_number(value, &options->repeat)) return false; }
        else if (key == "--conf") { if (!parse_number(value, &options->confidence)) return false; }
        else if (key == "--nms") { if (!parse_number(value, &options->nms)) return false; }
        else if (key == "--max-det") { if (!parse_number(value, &options->max_detections)) return false; }
        else if (key == "--target-classes") options->target_classes = value;
        else return false;
    }
    return !options->model.empty() && !options->input.empty() && options->repeat > 0;
}

bool read_file(const std::string &path, std::vector<unsigned char> *data) {
    std::ifstream input(path, std::ios::binary | std::ios::ate);
    if (!input) return false;
    const std::streamsize size = input.tellg();
    if (size < 0) return false;
    input.seekg(0);
    data->resize(static_cast<std::size_t>(size));
    return static_cast<bool>(input.read(reinterpret_cast<char *>(data->data()), size));
}

std::string escape_json_string(const std::string &text) {
    std::ostringstream out;
    for (char value : text) {
        if (value == '"' || value == '\\') out << '\\';
        out << value;
    }
    return out.str();
}

void emit_detections(int frame_index, const std::vector<BackendDetection> &detections) {
    std::cout << "{\"type\":\"detections\",\"frame_index\":" << frame_index << ",\"detections\":[";
    for (std::size_t index = 0; index < detections.size(); ++index) {
        if (index != 0) std::cout << ',';
        const BackendDetection &item = detections[index];
        std::cout << std::fixed << std::setprecision(4)
                  << "{\"class_id\":" << item.class_id
                  << ",\"class_name\":\"" << escape_json_string(backend_coco_class_name(item.class_id)) << "\""
                  << ",\"confidence\":" << item.score
                  << ",\"bbox\":[" << item.x1 << ',' << item.y1 << ',' << item.x2 << ',' << item.y2 << "]}";
    }
    std::cout << "]}" << std::endl;
}

}  // namespace

int main(int argc, char **argv) {
    Options options;
    if (!parse_options(argc, argv, &options)) {
        std::cerr << "usage: ss928_detection_runner --model MODEL.om --input FRAME.nv12 "
                     "--source-width W --source-height H [--repeat N --conf F --nms F --max-det N]\n";
        return 2;
    }
    std::string error;
    Ss928AclDetector detector;
    if (!detector.initialize(options.model, 0, &error)) {
        std::cerr << error << '\n';
        return 1;
    }
    std::vector<unsigned char> input;
    if (!read_file(options.input, &input) || input.size() != detector.input_bytes()) {
        std::cerr << "input must be an exact model-sized NV12 frame; expected " << detector.input_bytes() << " bytes\n";
        return 1;
    }
    LetterboxInfo letterbox;
    if (!compute_letterbox(options.source_width, options.source_height, 640, 640, &letterbox, &error)) {
        std::cerr << error << '\n';
        return 1;
    }
    const BackendTargetClassFilter filter = backend_parse_target_classes(options.target_classes);
    for (int frame = 0; frame < options.repeat; ++frame) {
        AclInferenceResult inference;
        if (!detector.infer(input.data(), input.size(), &inference, &error)) {
            std::cerr << error << '\n';
            return 1;
        }
        std::vector<BackendDetection> detections;
        YoloV8DecodeStats stats;
        if (!decode_yolov8(inference.output, inference.output_elements, inference.output_dims, letterbox,
                           filter, options.confidence, options.nms, options.max_detections,
                           &detections, &stats, &error)) {
            std::cerr << error << '\n';
            return 1;
        }
        emit_detections(frame, detections);
        std::cerr << "frame=" << frame << " infer_ms=" << inference.inference_ms
                  << " candidates=" << stats.raw_candidate_count << " detections=" << detections.size() << '\n';
    }
    return 0;
}
