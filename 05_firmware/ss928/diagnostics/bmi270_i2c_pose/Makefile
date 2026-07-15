CC ?= gcc
CFLAGS ?= -O2 -Wall -Wextra -std=c11
LDLIBS ?= -lm

TARGET := bmi270_i2c_pose
BMI270_CONFIG_INC ?= /opt/bosch/bmi270

all: $(TARGET)

$(TARGET): bmi270_i2c_pose.c
	$(CC) $(CFLAGS) -I"$(BMI270_CONFIG_INC)" -o $@ $< $(LDLIBS)

clean:
	rm -f $(TARGET)

.PHONY: all clean
