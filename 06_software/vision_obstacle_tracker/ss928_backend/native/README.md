# SS928 ACL native adapter

This shared library is the narrow C ABI between Python and the SS928 ACL
runtime. It owns one `.om` model for the process lifetime and accepts already
letterboxed model tensors from memory. It does not read temporary image files.

The adapter intentionally does not call `aclFinalize()` during shutdown. The
ACL version in the current board image crashes there after a successful model
unload. The detector process owns one runtime, so process exit is the cleanup
boundary until the vendor runtime is updated.

Build with the SS928 SDK headers and ARM `libascendcl.so`:

```sh
cmake -S . -B build \
  -DCMAKE_TOOLCHAIN_FILE=/path/to/aarch64-toolchain.cmake \
  -DSS928_NPU_INCLUDE_DIR=/path/to/sdk/include/hisilicon/npu \
  -DSS928_NPU_LIBRARY=/path/to/sdk/lib/linux/hisilicon/npu/libascendcl.so
cmake --build build --config Release
```

Do not use an OpenVINO export here. The runtime requires an SS928-compatible
`.om` model whose verified contract is one image input and one FP32
`1x84x8400` YOLO output.

The reproducible YOLO11 ONNX-to-OM procedure and SS928V100 AIPP configuration
are in `../model_conversion/README.md`. Generated model files are intentionally
excluded from Git.
