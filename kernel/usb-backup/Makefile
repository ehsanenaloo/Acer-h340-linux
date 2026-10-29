obj-m += acer_h340_usb_backup.o

KERNEL_RELEASE ?= $(shell uname -r)
KERNEL_BUILD ?= /lib/modules/$(KERNEL_RELEASE)/build

.PHONY: all clean
all:
	$(MAKE) -C $(KERNEL_BUILD) M=$(CURDIR) W=1 modules

clean:
	$(MAKE) -C $(KERNEL_BUILD) M=$(CURDIR) clean
