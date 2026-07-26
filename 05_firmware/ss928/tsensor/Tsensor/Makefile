include $(PWD)/Makefile.param

NFS_PATH ?= /root/Workspace/NFS/
APP_PATH := ./$(APP_TARGET)
OBJ_PATH := ./$(TARGET)_obj

PWD := $(shell pwd)

default: driver application obj

driver:
	@echo -e "\e[0;32;1m--Compiling '$(TARGET)'.ko... Configs as follow:\e[0;36;1m"
	@echo ---- CROSS_COMPILE=$(CROSS_COMPILE)
	@echo ---- ARCH=$(ARCH)
	@echo ---- PATH=$(PWD)
	@echo ---- KERNELDIR=$(KERNELDIR)
	@@echo -e "\e[0m"
	@$(MAKE) ARCH=$(ARCH) CROSS_COMPILE=$(CROSS_COMPILE) -C $(KERNELDIR) M=$(PWD) modules

application:
	@echo -e "\e[0;32;1m--Compiling '$(APP_TARGET)'... Configs as follow:\e[0;36;1m"
	@echo ---- CROSS_COMPILE=$(CROSS_COMPILE)
	@echo ---- ARCH=$(ARCH)
	@echo ---- PATH=$(PWD)
	@@echo -e "\e[0m"
	@$(CROSS_COMPILE)gcc -c $(TARGET_DRIVER)_uapi.c
	@$(CROSS_COMPILE)ar rcs $(LIB) $(TARGET_DRIVER)_uapi.o
	@mkdir -p $(APP_PATH)
	@mv $(LIB) $(APP_PATH)
	@cp $(APP_TARGET).c $(TARGET).ko $(TARGET_DRIVER)_uapi.h $(TARGET)_data_type.h Makefile.param $(APP_PATH)
	@cp APP_Makefile $(APP_PATH)/Makefile
	@cd $(APP_PATH) && make && cd ..
	@tar -cvJf $(APP_PATH).tar.xz $(APP_PATH)

obj:
	@mkdir -p $(OBJ_PATH)
	#@cp -rf *.o .*.o.cmd Makefile.param $(OBJ_PATH)
	@cp -rf $($(TARGET)-y) $(TARGET).o .*.o.cmd Makefile.param $(OBJ_PATH)
	@cp OBJ_Makefile $(OBJ_PATH)/Makefile
	@tar -cvJf $(OBJ_PATH).tar.xz $(OBJ_PATH)

obj_clean:
	@echo -e "\e[0;32;1m--Clean OBJ \e[0;36;1m"
	@@echo -e "\e[0m"
	@rm $(OBJ_PATH).tar.xz $(OBJ_PATH) -rf

nfs:
	@echo -e "\e[0;32;1m--Copy '$(TARGET)'.ko & '$(APP_TARGET)'... to NFS('$(NFS_PATH)')\e[0;36;1m"
	@@echo -e "\e[0m"
	@if [ -e $(TARGET).ko ]; then cp $(TARGET).ko $(NFS_PATH); fi
	@if [ -e $(APP_PATH)/$(APP_TARGET) ]; then cp $(APP_PATH)/$(APP_TARGET) $(NFS_PATH); fi

driver_clean:
	@echo -e "\e[0;32;1m--Clean Driver \e[0;36;1m"
	@@echo -e "\e[0m"
	@rm $(TARGET).ko *.mod.o  *.mod.c   Module.symvers *~  modules.order  *.o -rf .*.cmd *.mod

application_clean:
	@echo -e "\e[0;32;1m--Clean APP \e[0;36;1m"
	@@echo -e "\e[0m"
	@rm $(APP_PATH).tar.xz $(APP_PATH) -rf

nfs_clean:
	@echo -e "\e[0;32;1m--Clean NFS \e[0;36;1m"
	@@echo -e "\e[0m"
	@if [ -e $(NFS_PATH)/$(TARGET).ko ]; then rm $(NFS_PATH)/$(TARGET).ko; fi
	@if [ -e $(NFS_PATH)/$(APP_TARGET) ]; then rm $(NFS_PATH)/$(APP_TARGET); fi

clean: driver_clean application_clean obj_clean
