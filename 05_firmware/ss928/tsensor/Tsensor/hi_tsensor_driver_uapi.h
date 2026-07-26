///*****************************************
//   @file   <hi_tsensor_driver_uapi.h>
//   @author limingqiang@ebaina.com
//   @date   2025/07/02
//   @fileversion: Tsensor_Driver_V1.00
//******************************************/
#ifndef _HI_TSENSOR_DRIVER_API_H_
#define _HI_TSENSOR_DRIVER_API_H_

#ifdef __cplusplus
#if __cplusplus
extern "C" {
#endif
#endif /* End of #ifdef __cplusplus */

#include "hi_tsensor_data_type.h"

int hi_tsensor_device_init(void);
int hi_tsensor_get_data_info(hi_tsensor_data_info *data_info);
int hi_tsensor_device_exit(void);

#ifdef __cplusplus
#if __cplusplus
}
#endif
#endif /* End of #ifdef __cplusplus */

#endif
