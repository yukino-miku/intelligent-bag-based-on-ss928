CC ?= gcc
CXX ?= g++
CFLAGS ?= -std=c99 -Wall -Wextra -Werror -Iinclude
CXXFLAGS ?= -std=c++17 -Wall -Wextra -Werror -Iinclude
LDFLAGS ?= -lm

BUILD_DIR = build
CORE_SRC = src/vot.c
TEST_SRC = tests/test_core.c
APP_SRC = src/vision_obstacle_tracker_c.c

TEST_EXE = $(BUILD_DIR)/test_core.exe
BACKEND_TEST_EXE = $(BUILD_DIR)/test_backend.exe
APP_EXE = $(BUILD_DIR)/vision_obstacle_tracker_c.exe

.PHONY: all test backend-test app backend-status clean

all: test app

$(BUILD_DIR):
	mkdir $(BUILD_DIR)

$(TEST_EXE): $(BUILD_DIR) $(TEST_SRC) $(CORE_SRC) include/vot.h
	$(CC) $(CFLAGS) $(TEST_SRC) $(CORE_SRC) $(LDFLAGS) -o $(TEST_EXE)

$(APP_EXE): $(BUILD_DIR) $(APP_SRC) $(CORE_SRC) include/vot.h
	$(CC) $(CFLAGS) $(APP_SRC) $(CORE_SRC) $(LDFLAGS) -o $(APP_EXE)

test: $(TEST_EXE)
	$(TEST_EXE)

$(BACKEND_TEST_EXE): $(BUILD_DIR) tests/test_backend.cpp src/vot_backend.cpp include/vot_backend.h
	$(CXX) $(CXXFLAGS) tests/test_backend.cpp src/vot_backend.cpp -o $(BACKEND_TEST_EXE)

backend-test: $(BACKEND_TEST_EXE)
	$(BACKEND_TEST_EXE)

app: $(APP_EXE)

backend-status: $(APP_EXE)
	$(APP_EXE) --backend-status

clean:
	del /Q $(BUILD_DIR)\*.exe 2>NUL || exit 0
