///*****************************************
//   @file   <hi_tsensor_driver_uapi.c>
//   @author limingqiang@ebaina.com
//   @date   2025/07/02
//   @fileversion: Tsensor_Driver_V1.00
//******************************************/
#ifdef __cplusplus
#if __cplusplus
extern "C" {
#endif
#endif /* End of #ifdef __cplusplus */

#include <sys/fcntl.h>
#include <sys/stat.h>
#include <sys/ioctl.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>

#include "hi_tsensor_driver_uapi.h"
#include "hi_tsensor_driver_ioctrl.h"

static int g_hi_tsensor_fd = -1;

int hi_tsensor_device_init(void)
{
    if (g_hi_tsensor_fd != -1) {
        return 0;
    }

    g_hi_tsensor_fd = open(HI_TSENSOR_DEVICE, O_RDWR);
    if (g_hi_tsensor_fd < 0) {
        printf("Open %s failed!\n", HI_TSENSOR_DEVICE);
        g_hi_tsensor_fd = -1;
        return -1;
    }

    return 0;
}

int hi_tsensor_get_data_info(hi_tsensor_data_info *data_info)
{
    if (g_hi_tsensor_fd < 0) {
        printf("Device not inited !!!\n");
        return -1;
    }

    return ioctl(g_hi_tsensor_fd, HI_TSENSOR_CMD_GET_DATA_INFO, data_info);
}

int hi_tsensor_device_exit(void)
{
    if (g_hi_tsensor_fd > 0) {
        close(g_hi_tsensor_fd);
        g_hi_tsensor_fd = -1;
    }

    return 0;
}

#ifdef __cplusplus
#if __cplusplus
}
#endif
#endif /* End of #ifdef __cplusplus */
