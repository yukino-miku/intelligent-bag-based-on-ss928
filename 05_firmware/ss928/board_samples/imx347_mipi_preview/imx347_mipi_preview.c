/*
 * IMX347 sensor0 live preview on the 800x1280 MIPI panel.
 *
 * This sample keeps the board SDK untouched. It reuses the SDK MIPI panel
 * timing/command table from src/vdec/sample_vdec.c, then builds a live path:
 * VI(sensor0) -> VPSS -> VO(MIPI TX).
 *
 * Hardware target:
 * - EULER_4SEN V1.0 adapter
 * - sensor0 only, IMX347 2lane
 * - sensor0 I2C7
 */

#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "sample_comm.h"
#include "securec.h"

#ifndef MPP_VDEC_SAMPLE_C
#error "MPP_VDEC_SAMPLE_C must point to the SDK src/vdec/sample_vdec.c"
#endif

#ifndef SENSOR0_I2C_BUS
#define SENSOR0_I2C_BUS 7
#endif

#ifndef SENSOR0_LANE_DIVIDE_MODE
#define SENSOR0_LANE_DIVIDE_MODE LANE_DIVIDE_MODE_3
#endif

#define main sample_vdec_unused_main
#include MPP_VDEC_SAMPLE_C
#undef main

#define PREVIEW_VB_YUV_CNT 6
#define PREVIEW_VB_RAW_CNT 3
#define PREVIEW_VPSS_GRP 0
#define PREVIEW_VPSS_CHN 0
#define PREVIEW_VI_PIPE 0
#define PREVIEW_VI_CHN 0
#define PREVIEW_VI_DEV 0
#define PREVIEW_ROTATE_DISPLAY TD_TRUE
#define PREVIEW_DISPLAY_ROTATION OT_ROTATION_90

static volatile sig_atomic_t g_preview_exit = 0;

static td_void preview_handle_sig(td_s32 signo)
{
    if ((signo == SIGINT) || (signo == SIGTERM)) {
        g_preview_exit = 1;
    }
}

static td_s32 preview_sys_init(sample_sns_type sns_type)
{
    td_s32 ret;
    ot_size sns_size;
    ot_vb_cfg vb_cfg;
    ot_vb_calc_cfg calc_cfg;
    ot_pic_buf_attr buf_attr;

    sample_comm_vi_get_size_by_sns_type(sns_type, &sns_size);
    (td_void)memset_s(&vb_cfg, sizeof(vb_cfg), 0, sizeof(vb_cfg));
    vb_cfg.max_pool_cnt = 128;

    buf_attr.width = sns_size.width;
    buf_attr.height = sns_size.height;
    buf_attr.align = OT_DEFAULT_ALIGN;
    buf_attr.bit_width = OT_DATA_BIT_WIDTH_8;
    buf_attr.pixel_format = OT_PIXEL_FORMAT_YVU_SEMIPLANAR_420;
    buf_attr.compress_mode = OT_COMPRESS_MODE_SEG;
    ot_common_get_pic_buf_cfg(&buf_attr, &calc_cfg);
    vb_cfg.common_pool[0].blk_size = calc_cfg.vb_size;
    vb_cfg.common_pool[0].blk_cnt = PREVIEW_VB_YUV_CNT;

    buf_attr.pixel_format = OT_PIXEL_FORMAT_RGB_BAYER_12BPP;
    buf_attr.compress_mode = OT_COMPRESS_MODE_LINE;
    ot_common_get_pic_buf_cfg(&buf_attr, &calc_cfg);
    vb_cfg.common_pool[1].blk_size = calc_cfg.vb_size;
    vb_cfg.common_pool[1].blk_cnt = PREVIEW_VB_RAW_CNT;

    ret = sample_comm_sys_init_with_vb_supplement(&vb_cfg, OT_VB_SUPPLEMENT_BNR_MOT_MASK);
    if (ret != TD_SUCCESS) {
        sample_print("sys init failed: 0x%x\n", ret);
        return ret;
    }

    ret = sample_comm_vi_set_vi_vpss_mode(OT_VI_OFFLINE_VPSS_ONLINE, OT_VI_VIDEO_MODE_NORM);
    if (ret != TD_SUCCESS) {
        sample_print("set vi-vpss mode failed: 0x%x\n", ret);
        sample_comm_sys_exit();
    }

    return ret;
}

static td_void preview_get_sensor0_cfg(sample_sns_type sns_type, sample_vi_cfg *vi_cfg)
{
    sample_comm_vi_get_default_vi_cfg(sns_type, vi_cfg);

    vi_cfg->sns_info.bus_id = SENSOR0_I2C_BUS;
    vi_cfg->sns_info.sns_clk_src = 0;
    vi_cfg->sns_info.sns_rst_src = 0;
    vi_cfg->dev_info.vi_dev = PREVIEW_VI_DEV;
    vi_cfg->bind_pipe.pipe_id[0] = PREVIEW_VI_PIPE;
    vi_cfg->grp_info.grp_num = 1;
    vi_cfg->grp_info.fusion_grp[0] = 0;
    vi_cfg->grp_info.fusion_grp_attr[0].pipe_id[0] = PREVIEW_VI_PIPE;
    vi_cfg->pipe_info[0].chn_info[0].chn_attr.depth = 2;

    sample_comm_vi_get_mipi_info_by_dev_id(sns_type, PREVIEW_VI_DEV, &vi_cfg->mipi_info);
    vi_cfg->mipi_info.divide_mode = SENSOR0_LANE_DIVIDE_MODE;

    printf("sensor0 config: vi_dev=%d vi_pipe=%d vi_chn=%d i2c=%d clk=%d rst=%d lane_divide=%d\n",
        vi_cfg->dev_info.vi_dev,
        vi_cfg->bind_pipe.pipe_id[0],
        vi_cfg->pipe_info[0].chn_info[0].vi_chn,
        vi_cfg->sns_info.bus_id,
        vi_cfg->sns_info.sns_clk_src,
        vi_cfg->sns_info.sns_rst_src,
        vi_cfg->mipi_info.divide_mode);
}

static td_s32 preview_start_vpss(ot_vpss_grp grp, const ot_size *input_size, const ot_size *output_size)
{
    td_s32 ret;
    ot_vpss_grp_attr grp_attr;
    ot_vpss_chn_attr chn_attr;
    sample_comm_vpss_get_default_grp_attr(&grp_attr);
    grp_attr.max_width = input_size->width;
    grp_attr.max_height = input_size->height;

    sample_comm_vpss_get_default_chn_attr(&chn_attr);
    chn_attr.width = output_size->width;
    chn_attr.height = output_size->height;

    ret = ss_mpi_vpss_create_grp(grp, &grp_attr);
    if (ret != TD_SUCCESS) {
        sample_print("create vpss grp failed: 0x%x\n", ret);
        return ret;
    }

    ret = ss_mpi_vpss_start_grp(grp);
    if (ret != TD_SUCCESS) {
        sample_print("start vpss grp failed: 0x%x\n", ret);
        goto destroy_grp;
    }

    ret = ss_mpi_vpss_set_chn_attr(grp, PREVIEW_VPSS_CHN, &chn_attr);
    if (ret != TD_SUCCESS) {
        sample_print("set vpss chn attr failed: 0x%x\n", ret);
        goto stop_grp;
    }

    ret = ss_mpi_vpss_enable_chn(grp, PREVIEW_VPSS_CHN);
    if (ret != TD_SUCCESS) {
        sample_print("enable vpss chn failed: 0x%x\n", ret);
        goto stop_grp;
    }

    return TD_SUCCESS;

stop_grp:
    ss_mpi_vpss_stop_grp(grp);
destroy_grp:
    ss_mpi_vpss_destroy_grp(grp);
    return ret;
}

static td_void preview_stop_vpss(ot_vpss_grp grp)
{
    td_bool chn_enable[OT_VPSS_MAX_PHYS_CHN_NUM] = {TD_TRUE, TD_FALSE, TD_FALSE, TD_FALSE};
    sample_common_vpss_stop(grp, chn_enable, OT_VPSS_MAX_PHYS_CHN_NUM);
}

static td_s32 preview_calc_fit_rect(const ot_size *src_size, const ot_size *dst_size, ot_rect *rect)
{
    td_u32 out_width;
    td_u32 out_height;

    if ((src_size->width == 0) || (src_size->height == 0) ||
        (dst_size->width == 0) || (dst_size->height == 0)) {
        sample_print("invalid aspect size: src=%ux%u dst=%ux%u\n",
            src_size->width, src_size->height, dst_size->width, dst_size->height);
        return TD_FAILURE;
    }

    if ((td_u64)dst_size->width * src_size->height <= (td_u64)dst_size->height * src_size->width) {
        out_width = dst_size->width;
        out_height = (td_u32)(((td_u64)dst_size->width * src_size->height) / src_size->width);
    } else {
        out_height = dst_size->height;
        out_width = (td_u32)(((td_u64)dst_size->height * src_size->width) / src_size->height);
    }

    out_width &= ~1U;
    out_height &= ~1U;
    if ((out_width == 0) || (out_height == 0)) {
        sample_print("invalid keep-aspect output size: %ux%u\n", out_width, out_height);
        return TD_FAILURE;
    }

    rect->x = (td_s32)(((dst_size->width - out_width) / 2) & ~1U);
    rect->y = (td_s32)(((dst_size->height - out_height) / 2) & ~1U);
    rect->width = out_width;
    rect->height = out_height;
    return TD_SUCCESS;
}

static td_s32 preview_get_display_layout(const ot_size *input_size, const ot_size *panel_size,
    ot_size *vpss_output_size, ot_rect *vo_rect)
{
    ot_size display_src_size;
    td_s32 ret;

    if (PREVIEW_ROTATE_DISPLAY == TD_TRUE) {
        display_src_size.width = input_size->height;
        display_src_size.height = input_size->width;
    } else {
        display_src_size = *input_size;
    }

    ret = preview_calc_fit_rect(&display_src_size, panel_size, vo_rect);
    if (ret != TD_SUCCESS) {
        return ret;
    }

    if (PREVIEW_ROTATE_DISPLAY == TD_TRUE) {
        vpss_output_size->width = vo_rect->height;
        vpss_output_size->height = vo_rect->width;
    } else {
        vpss_output_size->width = vo_rect->width;
        vpss_output_size->height = vo_rect->height;
    }
    return TD_SUCCESS;
}

static td_s32 preview_start_vo_mipi_tx_from_vpss(const sample_vo_mipi_tx_cfg *vo_tx_cfg, td_u32 vpss_grp_num,
    const ot_rect *vo_rect)
{
    td_s32 ret;
    const sample_vo_cfg *vo_config = &vo_tx_cfg->vo_config;
    const sample_mipi_tx_config *tx_config = &vo_tx_cfg->tx_config;
    const ot_vo_dev vo_dev = vo_config->vo_dev;
    const ot_vo_layer vo_layer = vo_config->vo_dev;
    const ot_vo_chn vo_chn = 0;
    ot_vo_pub_attr vo_pub_attr = {0};
    ot_vo_video_layer_attr layer_attr = {0};
    ot_vo_chn_attr chn_attr = {0};

    chn_attr.rect = *vo_rect;
    chn_attr.priority = 0;
    chn_attr.deflicker_en = TD_FALSE;

    vo_pub_attr.intf_type = vo_config->vo_intf_type;
    vo_pub_attr.intf_sync = vo_config->intf_sync;
    vo_pub_attr.bg_color = vo_config->bg_color;
    (td_void)memcpy_s(&vo_pub_attr.sync_info, sizeof(ot_vo_sync_info),
        &vo_config->sync_info, sizeof(ot_vo_sync_info));

    layer_attr.cluster_mode_en = TD_FALSE;
    layer_attr.double_frame_en = TD_FALSE;
    layer_attr.pixel_format = vo_config->pix_format;
    layer_attr.display_rect = vo_config->disp_rect;
    layer_attr.img_size = vo_config->image_size;
    layer_attr.display_frame_rate = vo_config->dev_frame_rate;
    layer_attr.dst_dynamic_range = vo_config->dst_dynamic_range;
    layer_attr.display_buf_len = vo_config->dis_buf_len;
    layer_attr.partition_mode = vo_config->vo_part_mode;
    layer_attr.compress_mode = vo_config->compress_mode;

    ret = sample_comm_vo_start_dev(vo_dev, &vo_pub_attr, &vo_config->user_sync, vo_config->dev_frame_rate);
    if (ret != TD_SUCCESS) {
        sample_print("start vo dev failed: 0x%x\n", ret);
        return ret;
    }

    ret = sample_comm_vo_start_layer(vo_layer, &layer_attr);
    if (ret != TD_SUCCESS) {
        sample_print("start vo layer failed: 0x%x\n", ret);
        sample_comm_vo_stop_dev(vo_dev);
        return ret;
    }

    ret = ss_mpi_vo_set_chn_attr(vo_layer, vo_chn, &chn_attr);
    if (ret != TD_SUCCESS) {
        sample_print("set vo keep-aspect chn attr failed: 0x%x\n", ret);
        goto stop_layer;
    }

    if (PREVIEW_ROTATE_DISPLAY == TD_TRUE) {
        ret = ss_mpi_vo_set_chn_rotation(vo_layer, vo_chn, PREVIEW_DISPLAY_ROTATION);
        if (ret != TD_SUCCESS) {
            sample_print("set vo rotation failed: 0x%x\n", ret);
            goto stop_layer;
        }
    }

    ret = ss_mpi_vo_enable_chn(vo_layer, vo_chn);
    if (ret != TD_SUCCESS) {
        sample_print("enable vo chn failed: 0x%x\n", ret);
        goto stop_layer;
    }

    printf("start vo dhd%d.\n", vo_config->vo_dev);
    printf("VO keep-aspect rect: x=%d y=%d width=%u height=%u on panel=%ux%u\n",
        chn_attr.rect.x,
        chn_attr.rect.y,
        chn_attr.rect.width,
        chn_attr.rect.height,
        vo_config->disp_rect.width,
        vo_config->disp_rect.height);

    ret = sample_vpss_bind_vo(*vo_config, vpss_grp_num);
    if (ret != TD_SUCCESS) {
        sample_print("vpss bind vo failed: 0x%x\n", ret);
        goto disable_chn;
    }

    ret = sample_comm_start_mipi_tx(tx_config);
    if (ret != TD_SUCCESS) {
        sample_print("start mipi tx failed: 0x%x\n", ret);
        sample_vpss_unbind_vo(vpss_grp_num, *vo_config);
        goto disable_chn;
    }

    return TD_SUCCESS;

disable_chn:
    ss_mpi_vo_disable_chn(vo_layer, vo_chn);
stop_layer:
    sample_comm_vo_stop_layer(vo_layer);
    sample_comm_vo_stop_dev(vo_dev);
    return ret;
}

static td_void preview_stop_vo_mipi_tx_from_vpss(const sample_vo_mipi_tx_cfg *vo_tx_cfg, td_u32 vpss_grp_num)
{
    const sample_vo_cfg *vo_config = &vo_tx_cfg->vo_config;

    sample_vpss_unbind_vo(vpss_grp_num, *vo_config);
    sample_comm_stop_mipi_tx(vo_config->vo_intf_type);
    sample_comm_vo_stop_vo(vo_config);
}

static td_s32 preview_run(td_void)
{
    td_s32 ret;
    sample_sns_type sns_type = SENSOR0_TYPE;
    sample_vi_cfg vi_cfg;
    ot_size input_size;
    ot_size panel_size;
    ot_size vpss_output_size;
    ot_rect vo_rect;
    const sample_vo_mipi_tx_cfg *mipi_cfg = &g_vo_tx_cfg_800x1280_user;
    const ot_vpss_grp vpss_grp = PREVIEW_VPSS_GRP;
    const ot_vpss_chn vpss_chn = PREVIEW_VPSS_CHN;
    const td_u32 vpss_grp_num = 1;

    ret = preview_sys_init(sns_type);
    if (ret != TD_SUCCESS) {
        return ret;
    }

    preview_get_sensor0_cfg(sns_type, &vi_cfg);

    ret = sample_comm_vi_start_vi(&vi_cfg);
    if (ret != TD_SUCCESS) {
        sample_print("start vi failed: 0x%x\n", ret);
        goto stop_sys;
    }

    sample_comm_vi_get_size_by_sns_type(sns_type, &input_size);
    printf("sensor input size: %ux%u, display path: VI -> VPSS -> VO -> MIPI TX\n",
        input_size.width, input_size.height);

    panel_size.width = mipi_cfg->vo_config.disp_rect.width;
    panel_size.height = mipi_cfg->vo_config.disp_rect.height;
    ret = preview_get_display_layout(&input_size, &panel_size, &vpss_output_size, &vo_rect);
    if (ret != TD_SUCCESS) {
        goto stop_vi;
    }
    printf("display layout: rotate=%d vpss_out=%ux%u vo_rect={%d,%d,%u,%u}\n",
        PREVIEW_ROTATE_DISPLAY,
        vpss_output_size.width,
        vpss_output_size.height,
        vo_rect.x,
        vo_rect.y,
        vo_rect.width,
        vo_rect.height);

    ret = sample_comm_vi_bind_vpss(PREVIEW_VI_PIPE, PREVIEW_VI_CHN, vpss_grp, vpss_chn);
    if (ret != TD_SUCCESS) {
        sample_print("bind vi to vpss failed: 0x%x\n", ret);
        goto stop_vi;
    }

    ret = preview_start_vpss(vpss_grp, &input_size, &vpss_output_size);
    if (ret != TD_SUCCESS) {
        sample_print("start vpss failed: 0x%x\n", ret);
        goto unbind_vi_vpss;
    }

    (td_void)sample_vo_fix_hdmi_mipi_conflict();

    ret = preview_start_vo_mipi_tx_from_vpss(mipi_cfg, vpss_grp_num, &vo_rect);
    if (ret != TD_SUCCESS) {
        sample_print("start vo/mipi tx failed: 0x%x\n", ret);
        goto stop_vpss;
    }

    printf("IMX347 2lane sensor0 preview is running on MIPI 800x1280. Press Enter or Ctrl+C to stop.\n");
    while (!g_preview_exit) {
        if (getchar() == '\n') {
            break;
        }
    }

    preview_stop_vo_mipi_tx_from_vpss(mipi_cfg, vpss_grp_num);
stop_vpss:
    preview_stop_vpss(vpss_grp);
unbind_vi_vpss:
    sample_comm_vi_un_bind_vpss(PREVIEW_VI_PIPE, PREVIEW_VI_CHN, vpss_grp, vpss_chn);
stop_vi:
    sample_comm_vi_stop_vi(&vi_cfg);
stop_sys:
    sample_comm_sys_exit();
    return ret;
}

static td_void preview_usage(const char *name)
{
    printf("usage: %s\n", name);
    printf("sensor: default SONY_IMX347_2L_SLAVE_MIPI_2M_30FPS_12BIT on EULER_4SEN sensor0/I2C7\n");
    printf("display: 800x1280 MIPI panel timing reused from SDK vdec sample\n");
}

td_s32 main(td_s32 argc, td_char *argv[])
{
    td_s32 ret;

    if ((argc == 2) && (strncmp(argv[1], "-h", 2) == 0)) {
        preview_usage(argv[0]);
        return TD_SUCCESS;
    }

    if (argc != 1) {
        preview_usage(argv[0]);
        return TD_FAILURE;
    }

#ifndef __LITEOS__
    sample_sys_signal(preview_handle_sig);
#endif

    ret = preview_run();
    if ((ret == TD_SUCCESS) && (g_preview_exit == 0)) {
        printf("imx347_mipi_preview exit normally.\n");
    } else if (g_preview_exit != 0) {
        printf("imx347_mipi_preview stopped by signal.\n");
    } else {
        printf("imx347_mipi_preview exit abnormally: 0x%x.\n", ret);
    }

    return ret;
}
