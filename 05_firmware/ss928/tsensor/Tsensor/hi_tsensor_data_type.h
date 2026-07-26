///*****************************************
//   @file   <hi_tsensor_data_type.h>
//   @author limingqiang@ebaina.com
//   @date   2025/07/02
//   @fileversion: Tsensor_Driver_V1.00
//******************************************/
#ifndef _HI_TSENSOR_DATA_TYPE_H_
#define _HI_TSENSOR_DATA_TYPE_H_

#ifdef __cplusplus
#if __cplusplus
extern "C" {
#endif
#endif /* End of #ifdef __cplusplus */

#define HI_TSENSOR_VERSION_STR_LEN		8
#define HI_TSENSOR_CHN_NUM				3

typedef struct {
	unsigned char version_num;
	char version_str[HI_TSENSOR_VERSION_STR_LEN];
}hi_tsensor_version_info;

typedef struct {
	int is_valid[HI_TSENSOR_CHN_NUM];
	int temprature_data[HI_TSENSOR_CHN_NUM];
	unsigned int raw_data[HI_TSENSOR_CHN_NUM];
}hi_tsensor_data_info;

#ifdef __cplusplus
#if __cplusplus
}
#endif
#endif /* End of #ifdef __cplusplus */

#endif
