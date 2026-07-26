///*****************************************
//   @file   <hi_tsensor_driver_sample.c>
//   @author limingqiang@ebaina.com
//   @date   2025/07/02
//   @fileversion: Tsensor_Driver_V1.00
//******************************************/
#ifdef __cplusplus
#if __cplusplus
extern "C" {
#endif
#endif /* End of #ifdef __cplusplus */

#include <stdio.h>
#include <unistd.h>
#include <stdlib.h>
#include <fcntl.h>
#include <string.h>

#include "hi_tsensor_driver_uapi.h"

void demo_usage(void)
{
    printf("\n\n/************************************/\n");
    printf("please choose the case which you want to run:\n");
    printf("\t1:  hi_tsensor_get_data_info !\n");
    printf("\tq:  quit\n");
    printf("sample command:");
}

int main(void)
{
    int ret;
    int status = 0;
    char ch;
    char Exit = 0;
    int i;
    hi_tsensor_data_info data_info = {0};
    float temperature = 0;

    ret = hi_tsensor_device_init();
    if (ret < 0) {
        printf("hi_tsensor_device_init failed !\n");
        return -1;
    }

    while (1) {
        demo_usage();
        ch = getchar();
        if (10 == ch) {
            continue;
        }

        getchar();
        switch (ch) {
            case '1': {
                status = 0;
                memset(&data_info, 0, sizeof(hi_tsensor_data_info));
                ret = hi_tsensor_get_data_info(&data_info);
                if (ret == 0) {
                    for (i=0; i<HI_TSENSOR_CHN_NUM; i++) {
                        if (data_info.is_valid[i]) {
                            printf("TSENSOR[%d] DATA: %d \n", i, data_info.temprature_data[i]);
                            temperature = (((float)data_info.raw_data[i] - 146.0f) / 718.0f) * 165.0f - 40.0f;
                            printf("TSENSOR[%d] DATA: %02f \n", i, temperature);
                        } else {
                            printf("TSENSOR[%d] DATA: INVALIED \n", i);
                        }
                    }
                } else {
                    printf("hi_tsensor_get_data_info failed !\n");
                }
                break;
            }

            case 'q':
            case 'Q': {
                Exit = 1;
                break;
            }

            default : {
                printf("input invaild! please try again.\n");
                break;
            }
        }

        if (Exit) {
            break;
        }
    }

    ret = hi_tsensor_device_exit();
    if (ret < 0){
        printf("hi_tsensor_device_exit failed !\n");
        return -1;
    }
}

#ifdef __cplusplus
#if __cplusplus
}
#endif
#endif /* End of #ifdef __cplusplus */
