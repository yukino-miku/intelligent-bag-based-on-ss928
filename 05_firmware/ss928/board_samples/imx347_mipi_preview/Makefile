MPP_SAMPLE_ROOT ?= /opt/ss928/mpp/sample

SENSOR0_TYPE ?= SONY_IMX347_2L_SLAVE_MIPI_2M_30FPS_12BIT

include $(MPP_SAMPLE_ROOT)/src/Makefile.param

TARGET := imx347_mipi_preview
TARGET_PATH := $(PWD)
SMP_SRCS := $(wildcard $(PWD)/*.c)
OBJS := $(SMP_SRCS:%.c=%.o)

VDEC_SAMPLE_C := $(MPP_SAMPLE_ROOT)/src/vdec/sample_vdec.c

SENSOR0_I2C_BUS ?= 7
SENSOR0_LANE_DIVIDE_MODE ?= LANE_DIVIDE_MODE_3

CFLAGS += '-DMPP_VDEC_SAMPLE_C="$(VDEC_SAMPLE_C)"'
CFLAGS += -DSENSOR0_I2C_BUS=$(SENSOR0_I2C_BUS)
CFLAGS += -DSENSOR0_LANE_DIVIDE_MODE=$(SENSOR0_LANE_DIVIDE_MODE)

.PHONY: all clean

all: $(TARGET)

$(TARGET): $(COMM_OBJ) $(OBJS)
	$(CC) $(CFLAGS) -lpthread -lm -o $(TARGET_PATH)/$@ $^ -Wl,--start-group $(MPI_LIBS) $(AUDIO_LIBS) $(INIPARSER_LIB) -Wl,--end-group

clean:
	@rm -f $(TARGET_PATH)/$(TARGET)
	@rm -f $(OBJS)
	@rm -f $(COMM_OBJ)
