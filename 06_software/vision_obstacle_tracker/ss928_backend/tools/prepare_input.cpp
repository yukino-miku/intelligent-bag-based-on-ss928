#include "frame_preprocess.h"

#include <fstream>
#include <iostream>
#include <string>
#include <vector>

namespace {

bool read_ppm_bgr(const std::string &path, std::vector<unsigned char> *bgr, int *width, int *height) {
    std::ifstream input(path, std::ios::binary);
    std::string magic;
    int max_value = 0;
    if (!(input >> magic >> *width >> *height >> max_value) || magic != "P6" || *width <= 0 || *height <= 0 || max_value != 255) {
        return false;
    }
    input.get();
    std::vector<unsigned char> rgb(static_cast<std::size_t>(*width) * *height * 3);
    input.read(reinterpret_cast<char *>(rgb.data()), static_cast<std::streamsize>(rgb.size()));
    if (input.gcount() != static_cast<std::streamsize>(rgb.size())) {
        return false;
    }
    bgr->resize(rgb.size());
    for (std::size_t i = 0; i < rgb.size(); i += 3) {
        (*bgr)[i] = rgb[i + 2];
        (*bgr)[i + 1] = rgb[i + 1];
        (*bgr)[i + 2] = rgb[i];
    }
    return true;
}

bool write_binary(const std::string &path, const std::vector<unsigned char> &bytes) {
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    output.write(reinterpret_cast<const char *>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
    return static_cast<bool>(output);
}

bool write_ppm_rgb(const std::string &path, const std::vector<unsigned char> &bgr, int width, int height) {
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    output << "P6\n" << width << ' ' << height << "\n255\n";
    for (std::size_t i = 0; i < bgr.size(); i += 3) {
        const unsigned char rgb[3] = {bgr[i + 2], bgr[i + 1], bgr[i]};
        output.write(reinterpret_cast<const char *>(rgb), 3);
    }
    return static_cast<bool>(output);
}

bool write_meta(const std::string &path, const LetterboxInfo &info, std::size_t input_bytes) {
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    output << "{\n"
           << "  \"source_width\":" << info.source_width << ",\n"
           << "  \"source_height\":" << info.source_height << ",\n"
           << "  \"model_width\":" << info.model_width << ",\n"
           << "  \"model_height\":" << info.model_height << ",\n"
           << "  \"resized_width\":" << info.resized_width << ",\n"
           << "  \"resized_height\":" << info.resized_height << ",\n"
           << "  \"scale\":" << info.scale << ",\n"
           << "  \"pad_x\":" << info.pad_x << ",\n"
           << "  \"pad_y\":" << info.pad_y << ",\n"
           << "  \"input_format\":\"NV12\",\n"
           << "  \"input_bytes\":" << input_bytes << "\n"
           << "}\n";
    return static_cast<bool>(output);
}

}  // namespace

int main(int argc, char **argv) {
    if (argc != 5) {
        std::cerr << "Usage: " << argv[0] << " SOURCE.ppm INPUT.nv12 LETTERBOX.ppm META.json\n";
        return 2;
    }
    std::vector<unsigned char> source_bgr;
    int width = 0;
    int height = 0;
    if (!read_ppm_bgr(argv[1], &source_bgr, &width, &height)) {
        std::cerr << "could not read P6 PPM source: " << argv[1] << '\n';
        return 1;
    }
    std::vector<unsigned char> nv12;
    std::vector<unsigned char> preview;
    LetterboxInfo info{};
    std::string error;
    if (!bgr_letterbox_to_nv12(
            source_bgr.data(), source_bgr.size(), width, height, width * 3,
            640, 640, &nv12, &preview, &info, &error)) {
        std::cerr << "preprocess failed: " << error << '\n';
        return 1;
    }
    if (!write_binary(argv[2], nv12)
        || !write_ppm_rgb(argv[3], preview, info.model_width, info.model_height)
        || !write_meta(argv[4], info, nv12.size())) {
        std::cerr << "could not write one or more output files\n";
        return 1;
    }
    std::cout << "source=" << width << 'x' << height
              << " resized=" << info.resized_width << 'x' << info.resized_height
              << " scale=" << info.scale << " pad_x=" << info.pad_x << " pad_y=" << info.pad_y
              << " input_bytes=" << nv12.size() << '\n';
    return 0;
}
