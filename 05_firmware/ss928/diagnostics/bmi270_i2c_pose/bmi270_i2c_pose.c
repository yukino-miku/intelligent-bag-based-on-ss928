#define _DEFAULT_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <linux/i2c-dev.h>
#include <linux/i2c.h>
#include <math.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

#include "BMI270_config.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#define BMI270_CHIP_ID_VALUE 0x24

#define BMI270_REG_CHIP_ID 0x00
#define BMI270_REG_ACC_X_LSB 0x0C
#define BMI270_REG_INTERNAL_STATUS 0x21
#define BMI270_REG_TEMP_LSB 0x22
#define BMI270_REG_ACC_CONF 0x40
#define BMI270_REG_ACC_RANGE 0x41
#define BMI270_REG_GYR_CONF 0x42
#define BMI270_REG_GYR_RANGE 0x43
#define BMI270_REG_INIT_CTRL 0x59
#define BMI270_REG_INIT_ADDR_0 0x5B
#define BMI270_REG_INIT_ADDR_1 0x5C
#define BMI270_REG_INIT_DATA 0x5E
#define BMI270_REG_IF_CONF 0x6B
#define BMI270_REG_PWR_CONF 0x7C
#define BMI270_REG_PWR_CTRL 0x7D
#define BMI270_REG_CMD 0x7E

#define BMI270_ACC_RANGE_16G 0x03
#define BMI270_GYR_RANGE_2000DPS 0x00
#define BMI270_ODR_200HZ 0x09
#define BMI270_CONF_FILTER_PERF 0xA0

#define BMI270_CONFIG_CHUNK 32

struct bmi270_dev {
    int fd;
    uint8_t addr;
};

struct bmi270_sample {
    int16_t acc_x;
    int16_t acc_y;
    int16_t acc_z;
    int16_t gyr_x;
    int16_t gyr_y;
    int16_t gyr_z;
    int16_t temp_raw;
};

struct pose_state {
    float q0;
    float q1;
    float q2;
    float q3;
    float yaw_unwrapped;
    float yaw_last;
    bool yaw_ready;
};

static volatile sig_atomic_t g_stop = 0;

static void on_signal(int sig)
{
    (void)sig;
    g_stop = 1;
}

static void sleep_ms(unsigned int ms)
{
    usleep(ms * 1000u);
}

static double now_seconds(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1000000000.0;
}

static int parse_int(const char *text, long min_value, long max_value, long *out)
{
    char *end = NULL;
    errno = 0;
    long value = strtol(text, &end, 0);
    if (errno != 0 || end == text || *end != '\0' || value < min_value || value > max_value) {
        return -1;
    }
    *out = value;
    return 0;
}

static int i2c_write_bytes(const struct bmi270_dev *dev, uint8_t reg, const uint8_t *data, size_t len)
{
    uint8_t stack_buf[1 + BMI270_CONFIG_CHUNK];
    uint8_t *buf = stack_buf;

    if (len + 1 > sizeof(stack_buf)) {
        buf = malloc(len + 1);
        if (buf == NULL) {
            perror("malloc");
            return -1;
        }
    }

    buf[0] = reg;
    if (len > 0) {
        memcpy(buf + 1, data, len);
    }

    ssize_t written = write(dev->fd, buf, len + 1);
    if (buf != stack_buf) {
        free(buf);
    }

    if (written != (ssize_t)(len + 1)) {
        perror("i2c write");
        return -1;
    }

    return 0;
}

static int i2c_write_u8(const struct bmi270_dev *dev, uint8_t reg, uint8_t value)
{
    return i2c_write_bytes(dev, reg, &value, 1);
}

static int i2c_read_bytes(const struct bmi270_dev *dev, uint8_t reg, uint8_t *data, uint16_t len)
{
    struct i2c_msg msgs[2];
    struct i2c_rdwr_ioctl_data xfer;

    msgs[0].addr = dev->addr;
    msgs[0].flags = 0;
    msgs[0].len = 1;
    msgs[0].buf = &reg;

    msgs[1].addr = dev->addr;
    msgs[1].flags = I2C_M_RD;
    msgs[1].len = len;
    msgs[1].buf = data;

    xfer.msgs = msgs;
    xfer.nmsgs = 2;

    if (ioctl(dev->fd, I2C_RDWR, &xfer) < 0) {
        perror("i2c read");
        return -1;
    }

    return 0;
}

static int i2c_read_u8(const struct bmi270_dev *dev, uint8_t reg, uint8_t *value)
{
    return i2c_read_bytes(dev, reg, value, 1);
}

static int bmi270_upload_config(const struct bmi270_dev *dev)
{
    if (i2c_write_u8(dev, BMI270_REG_INIT_CTRL, 0x00) != 0) {
        return -1;
    }

    for (size_t pos = 0; pos < sizeof(bmi270_config_file); pos += BMI270_CONFIG_CHUNK) {
        size_t chunk = sizeof(bmi270_config_file) - pos;
        uint16_t init_addr = (uint16_t)(pos / 2u);

        if (chunk > BMI270_CONFIG_CHUNK) {
            chunk = BMI270_CONFIG_CHUNK;
        }

        if (i2c_write_u8(dev, BMI270_REG_INIT_ADDR_0, (uint8_t)(init_addr & 0x0Fu)) != 0 ||
            i2c_write_u8(dev, BMI270_REG_INIT_ADDR_1, (uint8_t)(init_addr >> 4)) != 0 ||
            i2c_write_bytes(dev, BMI270_REG_INIT_DATA, &bmi270_config_file[pos], chunk) != 0) {
            fprintf(stderr, "BMI270 config upload failed at byte %zu\n", pos);
            return -1;
        }
    }

    if (i2c_write_u8(dev, BMI270_REG_INIT_CTRL, 0x01) != 0) {
        return -1;
    }

    sleep_ms(150);
    return 0;
}

static int bmi270_init(const struct bmi270_dev *dev)
{
    uint8_t chip_id = 0;
    uint8_t status = 0;
    const uint8_t conf_200hz = BMI270_ODR_200HZ | BMI270_CONF_FILTER_PERF;

    sleep_ms(10);
    if (i2c_read_u8(dev, BMI270_REG_CHIP_ID, &chip_id) != 0) {
        return -1;
    }
    if (chip_id != BMI270_CHIP_ID_VALUE) {
        fprintf(stderr, "Unexpected BMI270 chip id: 0x%02X, expected 0x%02X\n",
                chip_id, BMI270_CHIP_ID_VALUE);
        return -1;
    }

    (void)i2c_write_u8(dev, BMI270_REG_CMD, 0xB6);
    sleep_ms(20);

    if (i2c_read_u8(dev, BMI270_REG_CHIP_ID, &chip_id) != 0 || chip_id != BMI270_CHIP_ID_VALUE) {
        fprintf(stderr, "BMI270 did not answer after soft reset\n");
        return -1;
    }

    if (i2c_write_u8(dev, BMI270_REG_PWR_CONF, 0x00) != 0) {
        return -1;
    }
    sleep_ms(2);

    if (bmi270_upload_config(dev) != 0) {
        return -1;
    }

    if (i2c_read_u8(dev, BMI270_REG_INTERNAL_STATUS, &status) != 0) {
        return -1;
    }
    if ((status & 0x01u) == 0) {
        fprintf(stderr, "BMI270 init file not accepted, INTERNAL_STATUS=0x%02X\n", status);
        return -1;
    }

    if (i2c_write_u8(dev, BMI270_REG_PWR_CTRL, 0x0E) != 0 ||
        i2c_write_u8(dev, BMI270_REG_IF_CONF, 0x00) != 0 ||
        i2c_write_u8(dev, BMI270_REG_GYR_RANGE, BMI270_GYR_RANGE_2000DPS) != 0 ||
        i2c_write_u8(dev, BMI270_REG_GYR_CONF, conf_200hz) != 0 ||
        i2c_write_u8(dev, BMI270_REG_ACC_RANGE, BMI270_ACC_RANGE_16G) != 0 ||
        i2c_write_u8(dev, BMI270_REG_ACC_CONF, conf_200hz) != 0) {
        return -1;
    }

    sleep_ms(10);
    return 0;
}

static int16_t le_s16(const uint8_t *p)
{
    return (int16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

static int bmi270_read_sample(const struct bmi270_dev *dev, struct bmi270_sample *sample)
{
    uint8_t data[12];
    uint8_t temp[2];

    if (i2c_read_bytes(dev, BMI270_REG_ACC_X_LSB, data, sizeof(data)) != 0) {
        return -1;
    }
    if (i2c_read_bytes(dev, BMI270_REG_TEMP_LSB, temp, sizeof(temp)) != 0) {
        return -1;
    }

    sample->acc_x = le_s16(data + 0);
    sample->acc_y = le_s16(data + 2);
    sample->acc_z = le_s16(data + 4);
    sample->gyr_x = le_s16(data + 6);
    sample->gyr_y = le_s16(data + 8);
    sample->gyr_z = le_s16(data + 10);
    sample->temp_raw = le_s16(temp);
    return 0;
}

static float clampf(float value, float min_value, float max_value)
{
    if (value < min_value) {
        return min_value;
    }
    if (value > max_value) {
        return max_value;
    }
    return value;
}

static void pose_init(struct pose_state *pose)
{
    pose->q0 = 1.0f;
    pose->q1 = 0.0f;
    pose->q2 = 0.0f;
    pose->q3 = 0.0f;
    pose->yaw_unwrapped = 0.0f;
    pose->yaw_last = 0.0f;
    pose->yaw_ready = false;
}

static void pose_update(struct pose_state *pose, const struct bmi270_sample *sample, float dt,
                        float *pitch, float *roll, float *yaw)
{
    const float acc_scale = 1.0f / 2048.0f;
    const float gyro_rad_scale = (float)M_PI / (180.0f * 16.4f);
    const float kp = 1.2f;
    const float ki = 0.01f;
    const float integral_limit = 0.5f;
    static float integral_x = 0.0f;
    static float integral_y = 0.0f;
    static float integral_z = 0.0f;

    float ax = (float)sample->acc_x * acc_scale;
    float ay = (float)sample->acc_y * acc_scale;
    float az = (float)sample->acc_z * acc_scale;
    float gx = (float)sample->gyr_x * gyro_rad_scale;
    float gy = (float)sample->gyr_y * gyro_rad_scale;
    float gz = (float)sample->gyr_z * gyro_rad_scale;

    float acc_mag = ax * ax + ay * ay + az * az;
    if (acc_mag > 0.01f) {
        float recip_norm = 1.0f / sqrtf(acc_mag);
        ax *= recip_norm;
        ay *= recip_norm;
        az *= recip_norm;

        float vx = 2.0f * (pose->q1 * pose->q3 - pose->q0 * pose->q2);
        float vy = 2.0f * (pose->q0 * pose->q1 + pose->q2 * pose->q3);
        float vz = pose->q0 * pose->q0 - pose->q1 * pose->q1 - pose->q2 * pose->q2 + pose->q3 * pose->q3;

        float ex = ay * vz - az * vy;
        float ey = az * vx - ax * vz;
        float ez = ax * vy - ay * vx;

        integral_x = clampf(integral_x + ex * dt, -integral_limit, integral_limit);
        integral_y = clampf(integral_y + ey * dt, -integral_limit, integral_limit);
        integral_z = clampf(integral_z + ez * dt, -integral_limit, integral_limit);

        gx += kp * ex + ki * integral_x;
        gy += kp * ey + ki * integral_y;
        gz += kp * ez + ki * integral_z;
    }

    float qdot0 = 0.5f * (-pose->q1 * gx - pose->q2 * gy - pose->q3 * gz);
    float qdot1 = 0.5f * ( pose->q0 * gx + pose->q2 * gz - pose->q3 * gy);
    float qdot2 = 0.5f * ( pose->q0 * gy - pose->q1 * gz + pose->q3 * gx);
    float qdot3 = 0.5f * ( pose->q0 * gz + pose->q1 * gy - pose->q2 * gx);

    pose->q0 += qdot0 * dt;
    pose->q1 += qdot1 * dt;
    pose->q2 += qdot2 * dt;
    pose->q3 += qdot3 * dt;

    float norm = 1.0f / sqrtf(pose->q0 * pose->q0 + pose->q1 * pose->q1 +
                              pose->q2 * pose->q2 + pose->q3 * pose->q3);
    pose->q0 *= norm;
    pose->q1 *= norm;
    pose->q2 *= norm;
    pose->q3 *= norm;

    *roll = atan2f(2.0f * (pose->q0 * pose->q1 + pose->q2 * pose->q3),
                   1.0f - 2.0f * (pose->q1 * pose->q1 + pose->q2 * pose->q2)) * 57.29578f;
    *pitch = asinf(clampf(2.0f * (pose->q0 * pose->q2 - pose->q3 * pose->q1),
                          -1.0f, 1.0f)) * 57.29578f;

    float current_yaw = atan2f(2.0f * (pose->q0 * pose->q3 + pose->q1 * pose->q2),
                               1.0f - 2.0f * (pose->q2 * pose->q2 + pose->q3 * pose->q3)) * 57.29578f;
    if (!pose->yaw_ready) {
        pose->yaw_unwrapped = current_yaw;
        pose->yaw_last = current_yaw;
        pose->yaw_ready = true;
    } else {
        float diff = current_yaw - pose->yaw_last;
        if (diff > 180.0f) {
            diff -= 360.0f;
        } else if (diff < -180.0f) {
            diff += 360.0f;
        }
        pose->yaw_unwrapped += diff;
        pose->yaw_last = current_yaw;
    }
    *yaw = pose->yaw_unwrapped;
}

static void usage(const char *prog)
{
    fprintf(stderr,
            "Usage: sudo %s [--dev /dev/i2c-0] [--addr 0x68] [--rate 200] [--no-init]\n"
            "Output CSV: pitch,roll,yaw,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps,temp_c,t_ms\n",
            prog);
}

int main(int argc, char **argv)
{
    const char *dev_path = "/dev/i2c-0";
    long addr_value = 0x68;
    long rate_value = 200;
    bool do_init = true;

    for (int i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "--dev") == 0 && i + 1 < argc) {
            dev_path = argv[++i];
        } else if (strcmp(argv[i], "--addr") == 0 && i + 1 < argc) {
            if (parse_int(argv[++i], 0x08, 0x77, &addr_value) != 0) {
                fprintf(stderr, "Invalid I2C address\n");
                return 1;
            }
        } else if (strcmp(argv[i], "--rate") == 0 && i + 1 < argc) {
            if (parse_int(argv[++i], 1, 400, &rate_value) != 0) {
                fprintf(stderr, "Invalid sample rate\n");
                return 1;
            }
        } else if (strcmp(argv[i], "--no-init") == 0) {
            do_init = false;
        } else if (strcmp(argv[i], "-h") == 0 || strcmp(argv[i], "--help") == 0) {
            usage(argv[0]);
            return 0;
        } else {
            usage(argv[0]);
            return 1;
        }
    }

    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);
    setvbuf(stdout, NULL, _IOLBF, 0);

    int fd = open(dev_path, O_RDWR);
    if (fd < 0) {
        perror(dev_path);
        return 1;
    }

    struct bmi270_dev dev = {
        .fd = fd,
        .addr = (uint8_t)addr_value,
    };

    if (ioctl(fd, I2C_SLAVE, dev.addr) < 0) {
        perror("I2C_SLAVE");
        close(fd);
        return 1;
    }

    if (do_init && bmi270_init(&dev) != 0) {
        close(fd);
        return 1;
    }

    printf("# BMI270 dev=%s addr=0x%02X rate=%ldHz init=%s\n",
           dev_path, dev.addr, rate_value, do_init ? "yes" : "no");
    printf("# pitch_deg,roll_deg,yaw_deg,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps,temp_c,t_ms\n");

    struct pose_state pose;
    pose_init(&pose);

    double start = now_seconds();
    double last = start;
    double period = 1.0 / (double)rate_value;

    while (!g_stop) {
        struct bmi270_sample sample;
        double loop_start = now_seconds();
        float pitch = 0.0f;
        float roll = 0.0f;
        float yaw = 0.0f;

        double dt_double = loop_start - last;
        if (dt_double <= 0.0 || dt_double > 0.1) {
            dt_double = period;
        }
        last = loop_start;

        if (bmi270_read_sample(&dev, &sample) != 0) {
            break;
        }

        pose_update(&pose, &sample, (float)dt_double, &pitch, &roll, &yaw);

        float ax_g = (float)sample.acc_x / 2048.0f;
        float ay_g = (float)sample.acc_y / 2048.0f;
        float az_g = (float)sample.acc_z / 2048.0f;
        float gx_dps = (float)sample.gyr_x / 16.4f;
        float gy_dps = (float)sample.gyr_y / 16.4f;
        float gz_dps = (float)sample.gyr_z / 16.4f;
        float temp_c = 23.0f + (float)sample.temp_raw / 512.0f;
        double t_ms = (loop_start - start) * 1000.0;

        printf("%.2f,%.2f,%.2f,%.5f,%.5f,%.5f,%.3f,%.3f,%.3f,%.2f,%.1f\n",
               pitch, roll, yaw, ax_g, ay_g, az_g, gx_dps, gy_dps, gz_dps, temp_c, t_ms);

        double elapsed = now_seconds() - loop_start;
        if (elapsed < period) {
            usleep((useconds_t)((period - elapsed) * 1000000.0));
        }
    }

    close(fd);
    return 0;
}
