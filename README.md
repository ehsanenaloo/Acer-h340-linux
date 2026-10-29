<div align="center">

# Acer H340 for Linux

**Make the front panel of an Acer easyStore H340 work again.**

The Acer Aspire easyStore H340 is a small home server that came with Windows Home Server. Its lamps and buttons only worked with that system. This project brings them back on Linux: the drive lamps, the system lamp, the USB Backup button with a safe one-touch copy, and the power button.

[![CI](https://github.com/ehsanenaloo/Acer-h340-linux/actions/workflows/ci.yml/badge.svg)](https://github.com/ehsanenaloo/Acer-h340-linux/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Debian%20%7C%20Ubuntu-informational.svg)](INSTALL.md)
[![Hardware](https://img.shields.io/badge/hardware-Acer%20H340-orange.svg)](#requirements-and-limits)
[![OpenMediaVault](https://img.shields.io/badge/OpenMediaVault-8-blue.svg)](#openmediavault)

</div>

## Why this project exists

Put Debian or OpenMediaVault on an H340 and the front of the box goes quiet. The drive lamps stay dark, the USB Backup button does nothing and the power button may be ignored. These packages fix that. Each part works on its own, and only the settings pages need OpenMediaVault.

---

## What you get

| Package | What it does |
|---|---|
| `acer-h340-usb-backup-dkms` | Turns the front USB Backup button into a normal Linux key press |
| `h340-leds` | Drives the front lamps from the real state of your disks and system |
| `h340-usb-backup` | Copies the USB device on the front port to a folder when you press the button |
| `openmediavault-h340` | Settings pages for all of the above in OpenMediaVault |

---

## The lamps

| Lamp | What you see |
|---|---|
| **Drive bays 1 to 4** | A blue pulse while the disk is in use. A red blink when SMART reports a problem or a known disk is missing. Steady purple for a new disk that is not mounted yet |
| **System (i)** | Steady blue when everything that is checked is fine. Blinking blue while the system starts or stops. Red for a failing disk, a hot CPU, a stopped fan or a failed system service |
| **USB** | Steady while a device is connected. A slow blink while copying. Three quick pulses and a pause for one minute after a verified copy, which means you can remove the device. A fast blink for one minute after a copy that did not finish. Off when nothing is connected |

The power lamp and the network lamp are driven by the firmware and the network card. They work without this project.

Each bay is a fixed SATA port, so you never assign disks to bays. The service reads the port and remembers which disks belong to the machine. A disk joins that list when it is mounted.

---

## One-touch USB copy

Plug a USB disk into the front port and press the USB Backup button.

- **Nothing starts by itself.** Plugging in a device never starts a copy. Only the button does.
- **The device is read-only.** It is mounted read-only and nothing is ever deleted or changed on it.
- **Every run is new.** Each copy goes to its own dated folder, so older copies stay as they are. Nothing is overwritten.
- **Every file is checked.** The service writes a temporary file, reads it back, compares a checksum and the size, and only then gives it its final name.
- **Space is checked first.** A run is refused if it would leave less free space than you set.
- **You can skip names.** Folders such as `System Volume Information` are skipped by default. You can add your own patterns.
- **You see the result.** The lamp tells you when it is safe to remove the device. The last result is kept in `/var/lib/h340-usb-backup/last-run.json` and shown on the status page.

---

## The power button

The H340 power button is a normal ACPI button handled by systemd. Many systems ignore it by default. You can choose what a short press does: shut down, sleep, or nothing. In OpenMediaVault this is a page of its own. On other systems it is one line in a logind file. See [INSTALL.md](INSTALL.md).

Sleep (suspend to memory) has not been tried on this model. Test it before you rely on it.

---

## OpenMediaVault

The plugin adds a menu **Services > H340 USB Backup** with four pages:

| Page | What you set or see |
|---|---|
| Backup | The shared folder for copies, a sub-folder, the free space to keep, a run name and the names to skip |
| LEDs | The lamp service on or off, and a button to forget disks that were removed |
| Power button | Shut down, sleep or nothing. This is the same setting as System > Power Management |
| Status | The state of the services, what each bay holds, the power button and the last copy |

---

## Install

On Debian or Ubuntu:

```bash
sudo apt install ./acer-h340-usb-backup-dkms_*.deb ./h340-leds_*.deb ./h340-usb-backup_*.deb
```

Add `./openmediavault-h340_*.deb` if you use OpenMediaVault. The full steps, with the two small settings files, are in [INSTALL.md](INSTALL.md).

To build the packages yourself you only need Python 3:

```bash
python3 tools/build_plugin.py
```

The `.deb` files appear in `dist/`.

---

## Requirements and limits

| | |
|---|---|
| Machine | Acer Aspire easyStore H340 with the WG945GCM board. The lamp service checks the board and refuses to start on anything else |
| System | Any systemd system for the services. The `.deb` packages are for Debian and Ubuntu |
| Tested on | Debian 13 with OpenMediaVault 8.5.12, kernels 6.12 and 7.2 |
| Needs | Python 3.11 or newer, `smartmontools`, `/dev/port`, and DKMS with kernel headers for the module |
| Conflicts | The lamp service will not start while `dme1737`, `gpio_ich` or `leds_ss4200` is loaded |
| Module signing | The DKMS module is signed with the DKMS key. On a system with Secure Boot you must enroll that key |
| Not included | Blinking purple while a disk is added or removed, the red blink for system recovery, and boot-stage diagnostics. The firmware owns those states |

---

## FAQ

**Does it work on other NAS boxes?** No. The lamp addresses are measured on the H340. The service refuses to run on other hardware.

**Does it work without OpenMediaVault?** Yes. Only the settings pages need it. See [INSTALL.md](INSTALL.md).

**Can a copy start by mistake?** No. The button is the only trigger. A device that is plugged in is never touched until you press it.

**Why is a lamp purple?** A disk is in a bay but is not mounted. The system has not taken it into use yet. Create a file system on it and mount it, and it turns blue.

**A removed disk still shows red. How do I clear it?** In OpenMediaVault, tick **Forget removed disks** on the LEDs page and save. Without OpenMediaVault, see [INSTALL.md](INSTALL.md).

**The kernel says the module is not signed.** That is a warning when Secure Boot is off. The H340 has a legacy BIOS, so it does not apply there.

---

## Safety

The lamp service writes to a few registers of the board through `/dev/port`. It checks the board and the chip before the first write. It writes only the lamp bits and checks each write by reading it back. It never changes the pin mode, the fan or the watchdog. When it stops normally it puts the lamp bits back to the state it found.

The copy service never deletes anything and never overwrites a file.

---

## Layout

```text
src/            the lamp service and the copy service
kernel/         the USB Backup button module
packaging/      the Debian packages for the module, the lamps and the copy service
omv-plugin/     the OpenMediaVault plugin
tools/          the package builder
.github/        community files, issue forms and workflows
```

---

## Documentation

| | |
|---|---|
| [Install](INSTALL.md) | Packages, settings files, the power button and other systems |
| [Changelog](CHANGELOG.md) | What changed |
| [Notice](NOTICE.md) | Licenses and credits |
| [Contributing](.github/CONTRIBUTING.md) | How to report a problem or send a change |
| [Support](.github/SUPPORT.md) | Where to ask |
| [Security](.github/SECURITY.md) | How to report a vulnerability |

---

## Contributing

Bug reports, fixes and reports from other H340 owners are welcome. Read [CONTRIBUTING.md](.github/CONTRIBUTING.md) first. By taking part you agree to the [Code of Conduct](.github/CODE_OF_CONDUCT.md).

If the project helps you, you can [buy me a coffee](https://buymeacoffee.com/enaloo). It is never expected.

---

## License

Copyright (c) 2026 Ehsan Enaloo. Released under the [MIT License](LICENSE). The kernel module is GPL-2.0-only. See [NOTICE.md](NOTICE.md).

Acer, Aspire and easyStore are trademarks of Acer Inc. This project is independent and has no link with Acer.

## About

Made by [Ehsan Enaloo](https://github.com/ehsanenaloo). Acer H340 for Linux gives the front lamps, the USB Backup button and the power button of an Acer easyStore H340 back to Debian and OpenMediaVault.

Topics: `acer` `h340` `easystore` `nas` `home-server` `openmediavault` `debian` `linux` `dkms` `led` `systemd`
