# Licenses and credits

| Part | License |
| --- | --- |
| The lamp service, the copy service, the OpenMediaVault plugin, the packaging and the build tool | MIT. See [LICENSE](LICENSE) |
| The kernel module in `kernel/usb-backup` and the module sources inside the `acer-h340-usb-backup-dkms` package | GPL-2.0-only. The SPDX line and `MODULE_LICENSE` in the source say so. The module is a separate work that runs inside the kernel, so the MIT terms do not apply to it |

## Register mapping

The addresses and bit masks of the lamps come from the open source project [mediasmartserverd](https://github.com/amd989/mediasmartserverd) (the fork by amd989, commit `1d14c639213816a3b1f369cce54f07716630c991`, files `led_acerh340.h` and `led_control_sch5127_base.h`). That project uses the zlib license, which allows this. Only the measured addresses and masks were taken from it. The code here is written separately. It does not run the upstream start-up routines, does not touch the watchdog and does not use its mount helper. Credit for the mapping belongs to the authors of that project.

The hardware monitor chip follows the Microchip SCH5127 data sheet. The kernel module uses the public ACPI and input interfaces of Linux. The OpenMediaVault plugin follows the layout of the official `openmediavault-usbbackup` and `openmediavault-ftp` plugins (GPL-3.0-or-later). Only the file layout and the conventions are followed. No code is copied.

## Trademarks

Acer, Aspire and easyStore are trademarks of Acer Inc. Windows Home Server is a trademark of Microsoft. OpenMediaVault is a project of its own authors. This project is independent. It has no link with these companies and they do not endorse it.

## Warranty

The lamp service writes to a few I/O registers on one machine, and the copy service mounts and reads removable disks. The software comes without warranty. See [LICENSE](LICENSE). It works only on the Acer Aspire easyStore H340 with the WG945GCM board, and it refuses to start on any other machine.
