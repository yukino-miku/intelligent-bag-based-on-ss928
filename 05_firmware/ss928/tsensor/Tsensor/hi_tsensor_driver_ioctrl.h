///*****************************************
//   @file   <hi_tsensor_driver_ioctrl.h>
//   @author limingqiang@ebaina.com
//   @date   2025/07/02
//   @fileversion: Tsensor_Driver_V1.00
//******************************************/

#ifndef _HI_TSENSOR_DRIVER_IOCTL_H_
#define _HI_TSENSOR_DRIVER_IOCTL_H_

#ifdef __cplusplus
#if __cplusplus
extern "C" {
#endif
#endif /* End of #ifdef __cplusplus */

#include <linux/ioctl.h>

#define HI_TSENSOR_DEV_NAME		"Tsensor"
#define HI_TSENSOR_DEVICE		"/dev/Tsensor"

#define HI_TSENSOR_IOC_MAGIC				't'
#define HI_TSENSOR_CMD_GET_DATA_INFO		_IOWR(HI_TSENSOR_IOC_MAGIC, 0x1, int)
#define HI_TSENSOR_CMD_DRIVER_VERSION		_IOWR(HI_TSENSOR_IOC_MAGIC, 0xFF, int)

#ifdef __cplusplus
#if __cplusplus
}
#endif
#endif /* End of #ifdef __cplusplus */

#endif
