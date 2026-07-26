///*****************************************
//   @file   <hi_tsensor_driver.c>
//   @author limingqiang@ebaina.com
//   @date   2025/07/02
//   @fileversion: Tsensor_Driver_V1.00
//******************************************/
#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/fs.h>
#include <linux/init.h>
#include <linux/of.h>
#include <asm/io.h>
#include <asm/uaccess.h>
#include <linux/gpio.h>
#include <linux/cdev.h>
#include <linux/device.h>
#include <linux/slab.h>
#include <linux/irq.h>
#include <asm/irq.h>
#include <linux/interrupt.h>
#include <linux/wait.h>
#include <linux/workqueue.h>
#include <linux/sched.h>
#include <linux/poll.h>
#include <asm-generic/poll.h>
#include <linux/input.h>
#include <asm/bitops.h>
#include <linux/timer.h>
#include <linux/errno.h>
#include <linux/miscdevice.h>
#include <linux/fcntl.h>
#include <linux/init.h>
#include <linux/delay.h>
#include <linux/proc_fs.h>
#include <linux/i2c.h>
#include <linux/i2c-dev.h>
#include <linux/version.h>

#include "hi_tsensor_driver_ioctrl.h"
#include "hi_tsensor_data_type.h"

#define	HI_TSENSOR_DRIVER_VERSION_NUM		0x10
#define	HI_TSENSOR_DRIVER_VERSION_STR		"V1.0"

#define TSENSOR_CTRL_BASE_OFFSET	0x1102E000
#define TSENSOR_CHN_BASE_OFFSET		0x100
#define TSENSOR_CHN0_OFFSET			(0*TSENSOR_CHN_BASE_OFFSET)
#define TSENSOR_CHN1_OFFSET			(1*TSENSOR_CHN_BASE_OFFSET)
#define TSENSOR_CHN2_OFFSET			(2*TSENSOR_CHN_BASE_OFFSET)
#define TSENSOR_CTRL0_OFFSET		0x0
#define TSENSOR_CTRL1_OFFSET		0x4
#define TSENSOR_CTRL2_OFFSET		0x8
#define TSENSOR_CTRL3_OFFSET		0xC
#define TSENSOR_CTRL4_OFFSET		0x10
#define TSENSOR_CTRL5_OFFSET		0x14
#define TSENSOR_INT_MASK_OFFSET		0x20
#define TSENSOR_INT_CLR_OFFSET		0x24
#define TSENSOR_INT_RAW_OFFSET		0x28
#define TSENSOR_INT_STAT_OFFSET		0x2C

#define sys_writel(addr, value) ((*((volatile unsigned int *)(addr))) = (value))
#define sys_read(addr) (*((volatile int *)(addr)))

#define sys_config_ioremap_return(reg_name, addr, reg_len)	\
	do {													\
		(reg_name) = (void *)ioremap((addr), (reg_len));	\
		if ((reg_name) == NULL) {							\
			return (-1);									\
		}													\
	} while (0)

#define sys_config_iounmap(reg_name)	\
	do {								\
		if ((reg_name) != NULL) {		\
			iounmap((reg_name));		\
			(reg_name) = 0;				\
		}								\
	} while (0)

static void *g_reg_base = 0;
struct semaphore g_hi_tsensor_lock;

static void hi_tsensor_reg_init(void)
{
	int i = 0;
	unsigned int reg_data = 0;

	for (i=0; i<HI_TSENSOR_CHN_NUM; i++) {
		//Step1:设置T-Sensor采集模式为连续模式
		reg_data = sys_read(g_reg_base+TSENSOR_CTRL0_OFFSET+TSENSOR_CHN_BASE_OFFSET*i)&0xFFFFFFFF;
		reg_data |= 1<<30;
		sys_writel(g_reg_base+TSENSOR_CTRL0_OFFSET+TSENSOR_CHN_BASE_OFFSET*i, reg_data);

		//Step2:设置循环采集周期
		reg_data = sys_read(g_reg_base+TSENSOR_CTRL0_OFFSET+TSENSOR_CHN_BASE_OFFSET*i)&0xFFFFFFFF;
		reg_data = ~(0xFF << 20);
		reg_data |= ((100 & 0xFF) << 20);
		sys_writel(g_reg_base+TSENSOR_CTRL0_OFFSET+TSENSOR_CHN_BASE_OFFSET*i, reg_data);

		//Step3:使能T-Sensor，开始温度采集
		reg_data = sys_read(g_reg_base+TSENSOR_CTRL0_OFFSET+TSENSOR_CHN_BASE_OFFSET*i)&0xFFFFFFFF;
		reg_data |= 1<<31;
		sys_writel(g_reg_base+TSENSOR_CTRL0_OFFSET+TSENSOR_CHN_BASE_OFFSET*i, reg_data);
	}
}

static void hi_tsensor_get_temprature_data(hi_tsensor_data_info *data_info)
{
	int i = 0;
	unsigned int reg_data = 0;

	//循环模式，只读取最新的温度
	for (i=0; i<HI_TSENSOR_CHN_NUM; i++) {
		reg_data = sys_read(g_reg_base+TSENSOR_CTRL2_OFFSET+TSENSOR_CHN_BASE_OFFSET*i);
		reg_data &=0x3FF;
		if ((reg_data<146)||(reg_data>864)) {
			data_info->is_valid[i] = 0;
			data_info->temprature_data[i] = 0;
			data_info->raw_data[i] = 0;
		} else {
			data_info->is_valid[i] = 1;
			//data_info->temprature_data[i] = (((reg_data-146)/718)*165)-40;
			data_info->temprature_data[i] = ((reg_data-146)*165)/718-40;
			data_info->raw_data[i] = reg_data;
		}
	}
}

static void hi_tsensor_seq_printf(struct seq_file *pseq_file, const char *fmt, ...)
{
	va_list args;

	if (pseq_file == NULL) {
		printk("[%s] - parameter invalid!\n", __FUNCTION__);
		return;
	}

	va_start(args, fmt);
#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 3, 0)
	(void)seq_vprintf(pseq_file, fmt, args);
#else
	seq_vprintf(pseq_file, fmt, args);
#endif
	va_end(args);
}

static int hi_tsensor_proc_show(struct seq_file *pseq_file, void *pdata)
{
	int ret = 0;
	int i = 0;
	hi_tsensor_data_info data_info = {0};

	down(&g_hi_tsensor_lock);
	hi_tsensor_get_temprature_data(&data_info);
	up(&g_hi_tsensor_lock);

	hi_tsensor_seq_printf(pseq_file, "\t [HI_TSENSOR_DRIVER_VERSION:"HI_TSENSOR_DRIVER_VERSION_STR"], Build Time["__DATE__", "__TIME__"]\n");
	hi_tsensor_seq_printf(pseq_file, "\t [HI_TSENSOR driver is powered by www.ebaina.com !]\n");
	hi_tsensor_seq_printf(pseq_file, "\t\t TSENSOR DATA \n");

	for (i=0; i<HI_TSENSOR_CHN_NUM; i++) {
		if (data_info.is_valid[i]) {
			hi_tsensor_seq_printf(pseq_file, "\t TSENSOR[%d] DATA: %d \n", i, data_info.temprature_data[i]);
		} else {
			hi_tsensor_seq_printf(pseq_file, "\t TSENSOR[%d] DATA: INVALIED \n", i);
		}
	}

	return ret;
}

int hi_tsensor_proc_operations_open(struct inode * inode, struct file * pfile)
{
	return single_open(pfile, hi_tsensor_proc_show, NULL);
}

int hi_tsensor_proc_operations_close(struct inode * inode, struct file * pfile)
{
	return single_release(inode, pfile);
}

ssize_t hi_tsensor_proc_operations_read(struct file *pfile, char __user *ubuf, size_t size, loff_t *ploff_t)
{
	return seq_read(pfile, ubuf, size, ploff_t);
}

ssize_t hi_tsensor_proc_operations_write(struct file *pfile, const char __user *ubuf, size_t size, loff_t *ploff_t)
{
	return 0;
}

int hi_tsensor_file_operation_open(struct inode * inode, struct file * file)
{
	return 0;
}

int hi_tsensor_file_operation_close(struct inode * inode, struct file * file)
{
	return 0;
}

ssize_t hi_tsensor_file_operation_read(struct file *file, char __user *ubuf, size_t size, loff_t *loff_t)
{
	return 0;
}

ssize_t hi_tsensor_file_operation_write(struct file *file, const char __user *ubuf, size_t size, loff_t *loff_t)
{
	return 0;
}

long hi_tsensor_file_operation_ioctrl(struct file *file, unsigned int cmd, unsigned long argp)
{
	hi_tsensor_data_info data_info = {0};

	down(&g_hi_tsensor_lock);
	switch (cmd) {
		case HI_TSENSOR_CMD_GET_DATA_INFO:
			hi_tsensor_get_temprature_data(&data_info);
			if (copy_to_user((void*)argp, &data_info, sizeof(hi_tsensor_data_info))) {
				return -EFAULT;
			}
			break;

		default:
			printk("NO CMD!\n");
			break;
	}
	up(&g_hi_tsensor_lock);
	return 0;
}

static struct file_operations hi_tsensor_file_operations = {
	.owner = THIS_MODULE,
	.unlocked_ioctl = hi_tsensor_file_operation_ioctrl,
	.open = hi_tsensor_file_operation_open,
	.release = hi_tsensor_file_operation_close,
	.read = hi_tsensor_file_operation_read,
	.write = hi_tsensor_file_operation_write
};

#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 10, 0)
static struct file_operations hi_tsensor_proc_operations = {
	.owner = THIS_MODULE,
	.open = hi_tsensor_proc_operations_open,
	.release = hi_tsensor_proc_operations_close,
	.read = hi_tsensor_proc_operations_read,
	.write = hi_tsensor_proc_operations_write
};
#else
static struct proc_ops hi_tsensor_proc_operations = {
	.proc_open = hi_tsensor_proc_operations_open,
	.proc_release = hi_tsensor_proc_operations_close,
	.proc_read = hi_tsensor_proc_operations_read,
	.proc_write = hi_tsensor_proc_operations_write
};
#endif

static struct miscdevice hi_tsensor_miscdevice =
{
	.minor = MISC_DYNAMIC_MINOR,
	.name  = HI_TSENSOR_DEV_NAME,
	.fops = &hi_tsensor_file_operations,
};

struct proc_dir_entry *parent_proc_entry = NULL;

static int hi_tsensor_proc_init(const char *name)
{
	int ret = 0;
	struct proc_dir_entry *pentry = NULL;

#if 0
#if LINUX_VERSION_CODE < KERNEL_VERSION(3, 18, 0)
	parent_proc_entry = proc_mkdir("LINUX", NULL);
#else
	parent_proc_entry = proc_mkdir_data("LINUX", 0, NULL, NULL);
#endif
	if (parent_proc_entry == NULL) {
		printk("[%s]:proc_mkdir failed !\n", __FUNCTION__);
		return -EINVAL;
	}
#endif

#if LINUX_VERSION_CODE < KERNEL_VERSION(3, 18, 0)
	pentry = create_proc_entry(name, 0, parent_proc_entry);
#else
	pentry = proc_create(name, 0, parent_proc_entry, &hi_tsensor_proc_operations);
#endif

	if (pentry == NULL) {
		printk("[%s]:proc_create failed !\n", __FUNCTION__);
		return -EINVAL;
	}

	return ret;
}

static int hi_tsensor_proc_exit(const char *name)
{
	int ret = 0;

	remove_proc_entry(name, parent_proc_entry);

	return ret;
}

static int __init hi_tsensor_driver_init(void)
{
	int ret;

	sema_init(&g_hi_tsensor_lock, 1);

	ret = misc_register(&hi_tsensor_miscdevice);
	if (0 != ret) {
		printk("Insmod %s.ko failed !!! \r\n", HI_TSENSOR_DEV_NAME);
		goto INIT_ERROR;
	}
	hi_tsensor_proc_init(HI_TSENSOR_DEV_NAME);
	sys_config_ioremap_return(g_reg_base, TSENSOR_CTRL_BASE_OFFSET, 0x1000);
	hi_tsensor_reg_init();

	return 0;

INIT_ERROR:

	return -1;
}

static void __exit hi_tsensor_driver_exit(void)
{
	sys_config_iounmap(g_reg_base);
	hi_tsensor_proc_exit(HI_TSENSOR_DEV_NAME);
	misc_deregister(&hi_tsensor_miscdevice);
	printk("Rmmod %s.ko OK !!! \r\n", HI_TSENSOR_DEV_NAME);
}

module_init(hi_tsensor_driver_init);
module_exit(hi_tsensor_driver_exit);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("limingqiang@ebaina.com");
