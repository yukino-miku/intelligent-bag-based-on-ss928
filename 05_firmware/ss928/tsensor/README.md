# SS928 Tsensor 内核模块来源

本目录保留来源仓库 `work/tsensor_module_build` 的驱动源代码和 WSL 构建脚本，
不提交可重建的 `.ko`。驱动加载后由 `/proc/Tsensor` 暴露三个温度通道，板端
读取入口位于 `06_software/board_runtime/temperature/temperature_reader.py`。

这些 Makefile 依赖与开发板内核完全匹配的源码树和交叉工具链。编译、加载前
必须核对板端 `uname -r`；不同内核构建出的模块不能混用。
