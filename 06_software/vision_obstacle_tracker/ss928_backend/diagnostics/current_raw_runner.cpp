#include "ss928_acl_detector.h"

#include <fstream>
#include <iostream>
#include <string>
#include <vector>

namespace {

bool read_all(const std::string &path, std::vector<unsigned char> *bytes) {
    std::ifstream input(path, std::ios::binary | std::ios::ate);
    if (!input) return false;
    const std::streamoff size = input.tellg();
    if (size < 0) return false;
    bytes->resize(static_cast<std::size_t>(size));
    input.seekg(0);
    input.read(reinterpret_cast<char *>(bytes->data()), size);
    return static_cast<bool>(input) || size == 0;
}

bool write_all(const std::string &path, const void *data, std::size_t bytes) {
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    output.write(static_cast<const char *>(data), static_cast<std::streamsize>(bytes));
    return static_cast<bool>(output);
}

}  // namespace

int main(int argc, char **argv) {
    if (argc != 4) {
        std::cerr << "Usage: " << argv[0] << " MODEL INPUT_RAW OUTPUT_PREFIX\n";
        return 2;
    }
    const std::string model_path = argv[1];
    const std::string input_path = argv[2];
    const std::string output_path = std::string(argv[3]) + ".output0.bin";

    std::vector<unsigned char> input;
    if (!read_all(input_path, &input)) {
        std::cerr << "could not read input: " << input_path << '\n';
        return 1;
    }

    Ss928AclDetector detector;
    std::string error;
    if (!detector.initialize(model_path, 0, &error)) {
        std::cerr << error << '\n';
        return 1;
    }
    AclInferenceResult result;
    if (!detector.infer(input.data(), input.size(), &result, &error)) {
        std::cerr << error << '\n';
        return 1;
    }
    const std::size_t output_bytes = result.output_elements * sizeof(float);
    if (!write_all(output_path, result.output, output_bytes)) {
        std::cerr << "could not write output: " << output_path << '\n';
        return 1;
    }

    std::cout << "runner=current_acl_wrapper input_path=" << input_path
              << " input_bytes=" << input.size()
              << " output_count=1 output[0].path=" << output_path
              << " output[0].bytes=" << output_bytes
              << " output[0].dims=";
    for (std::size_t i = 0; i < result.output_dims.size(); ++i) {
        if (i != 0) std::cout << ',';
        std::cout << result.output_dims[i];
    }
    std::cout << " inference_ms=" << result.inference_ms << '\n';
    return 0;
}
