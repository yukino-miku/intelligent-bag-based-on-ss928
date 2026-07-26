ifeq ($(OS),Windows_NT)
SHELL := powershell.exe
.SHELLFLAGS := -NoProfile -Command
mkdir_p = New-Item -ItemType Directory -Force -Path '$(1)' | Out-Null
clean_dirs = if (Test-Path -LiteralPath '$(BUILD_DIR)') { Remove-Item -Recurse -Force -LiteralPath '$(BUILD_DIR)' }; if (Test-Path -LiteralPath '$(BIN_DIR)') { Remove-Item -Recurse -Force -LiteralPath '$(BIN_DIR)' }
else
SHELL := /bin/sh
mkdir_p = mkdir -p $(1)
clean_dirs = rm -rf $(BUILD_DIR) $(BIN_DIR)
endif

BUILD_DIR := build
BIN_DIR := bin
C_PORT_DIR := ../c_port
NATIVE_CXX ?= g++
NATIVE_CXXFLAGS ?= -std=c++14 -O2 -Wall -Wextra -Werror -Iinclude -I$(C_PORT_DIR)/include
CROSS_COMPILE ?= /opt/linux/x86-arm/aarch64-mix210-linux/bin/aarch64-mix210-linux-
TARGET_CXX := $(CROSS_COMPILE)g++
SDK_ROOT ?= /opt/ss928-sdk/mpp_sample
ACL_INCLUDE := $(SDK_ROOT)/include/hisilicon/npu
ACL_STUB_DIR := $(SDK_ROOT)/lib/linux/hisilicon/npu/stub
TARGET_CXXFLAGS ?= -std=c++14 -O2 -Wall -Wextra -Werror -fPIE -mcpu=cortex-a53 -Iinclude -I$(C_PORT_DIR)/include -I$(SDK_ROOT)/include/hisilicon -I$(ACL_INCLUDE)
TARGET_LDFLAGS ?= -pie -L$(ACL_STUB_DIR) -Wl,-rpath-link,$(ACL_STUB_DIR) -lascendcl -lpthread -lm -ldl

.PHONY: all native-tests runner om-inspect raw-diagnostics clean

all: native-tests runner om-inspect

$(BUILD_DIR) $(BIN_DIR):
	$(call mkdir_p,$@)

$(BUILD_DIR)/test_model_tensor_info: tests/test_model_tensor_info.cpp src/model_tensor_info.cpp | $(BUILD_DIR)
	$(NATIVE_CXX) $(NATIVE_CXXFLAGS) $^ -o $@

$(BUILD_DIR)/test_preprocess: tests/test_preprocess.cpp src/frame_preprocess.cpp | $(BUILD_DIR)
	$(NATIVE_CXX) $(NATIVE_CXXFLAGS) $^ -o $@

$(BUILD_DIR)/test_yolov8_decode: tests/test_yolov8_decode.cpp src/yolov8_postprocess.cpp src/frame_preprocess.cpp $(C_PORT_DIR)/src/vot_backend.cpp | $(BUILD_DIR)
	$(NATIVE_CXX) $(NATIVE_CXXFLAGS) $^ -o $@

$(BUILD_DIR)/test_acl_contract: tests/test_acl_contract.cpp src/ss928_acl_detector.cpp src/model_tensor_info.cpp | $(BUILD_DIR)
	$(NATIVE_CXX) $(NATIVE_CXXFLAGS) -DSS928_ACL_CONTRACT_ONLY $^ -o $@

native-tests: $(BUILD_DIR)/test_model_tensor_info $(BUILD_DIR)/test_preprocess $(BUILD_DIR)/test_yolov8_decode $(BUILD_DIR)/test_acl_contract
	./$(BUILD_DIR)/test_model_tensor_info
	./$(BUILD_DIR)/test_preprocess
	./$(BUILD_DIR)/test_yolov8_decode
	./$(BUILD_DIR)/test_acl_contract

RUNNER_SOURCES := src/detection_runner.cpp src/model_tensor_info.cpp src/ss928_acl_detector.cpp src/frame_preprocess.cpp src/yolov8_postprocess.cpp $(C_PORT_DIR)/src/vot_backend.cpp

$(BIN_DIR)/ss928_detection_runner: $(RUNNER_SOURCES) | $(BIN_DIR)
	$(TARGET_CXX) $(TARGET_CXXFLAGS) $(RUNNER_SOURCES) -o $@ $(TARGET_LDFLAGS)

runner: $(BIN_DIR)/ss928_detection_runner

$(BIN_DIR)/om_inspect: tools/om_inspect.cpp src/model_tensor_info.cpp | $(BIN_DIR)
	$(TARGET_CXX) $(TARGET_CXXFLAGS) $^ -o $@ $(TARGET_LDFLAGS)

om-inspect: $(BIN_DIR)/om_inspect

$(BIN_DIR)/current_raw_runner: diagnostics/current_raw_runner.cpp src/ss928_acl_detector.cpp src/model_tensor_info.cpp | $(BIN_DIR)
	$(TARGET_CXX) $(TARGET_CXXFLAGS) $^ -o $@ $(TARGET_LDFLAGS)

$(BIN_DIR)/reference_raw_runner: diagnostics/reference_raw_runner.cpp | $(BIN_DIR)
	$(TARGET_CXX) $(TARGET_CXXFLAGS) $^ -o $@ $(TARGET_LDFLAGS)

raw-diagnostics: $(BIN_DIR)/current_raw_runner $(BIN_DIR)/reference_raw_runner

clean:
	$(clean_dirs)
