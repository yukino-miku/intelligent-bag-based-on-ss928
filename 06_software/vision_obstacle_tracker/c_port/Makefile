CC ?= gcc
CFLAGS ?= -std=c99 -Wall -Wextra -Werror -Iinclude
LDFLAGS ?= -lm

BUILD_DIR = build
CORE_SRC = src/vot.c
TEST_SRC = tests/test_core.c
APP_SRC = src/vision_obstacle_tracker_c.c

TEST_EXE = $(BUILD_DIR)/test_core.exe
APP_EXE = $(BUILD_DIR)/vision_obstacle_tracker_c.exe

.PHONY: all test app backend-status clean

all: test app

$(BUILD_DIR):
	mkdir $(BUILD_DIR)

$(TEST_EXE): $(BUILD_DIR) $(TEST_SRC) $(CORE_SRC) include/vot.h
	$(CC) $(CFLAGS) $(TEST_SRC) $(CORE_SRC) $(LDFLAGS) -o $(TEST_EXE)

$(APP_EXE): $(BUILD_DIR) $(APP_SRC) $(CORE_SRC) include/vot.h
	$(CC) $(CFLAGS) $(APP_SRC) $(CORE_SRC) $(LDFLAGS) -o $(APP_EXE)

test: $(TEST_EXE)
	$(TEST_EXE)

app: $(APP_EXE)

backend-status: $(APP_EXE)
	$(APP_EXE) --backend-status

clean:
	del /Q $(BUILD_DIR)\*.exe 2>NUL || exit 0
