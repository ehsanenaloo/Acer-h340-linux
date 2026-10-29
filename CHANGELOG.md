# Changelog

All notable changes to this project are listed here.

The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.0] - 2026-10-28

The first public release.

### Added

- Lamp service for the Acer Aspire easyStore H340. Drive lamps pulse blue with disk activity, blink red for a failing or missing disk and stay purple for a new disk that is not mounted yet. The system lamp shows startup, a ready system and faults from disk health, CPU temperature, the fan and the system services.
- Bays come from the SATA ports. The service remembers which disks belong to the machine and learns a disk when it is mounted. Removed disks can be forgotten.
- Front USB lamp: steady when a device is connected, a slow blink while copying, three quick pulses and a pause for one minute after a verified copy, and a fast blink for one minute after a copy that did not finish.
- One-touch USB copy. The button starts a copy of the device on the front port into a new dated folder. The device is mounted read-only. Nothing is deleted or overwritten. Every file is written to a temporary name, read back, compared and then renamed. Free space is checked first. File and folder names can be skipped.
- Kernel module that turns the USB Backup button into a Linux key press, packaged for DKMS.
- Power button choice in OpenMediaVault: shut down, sleep or nothing. A status line shows the action the system really uses and warns about a manual file that overrides it.
- OpenMediaVault plugin with pages for the copy settings, the lamps, the power button and a status page that shows the services, the bays and the last copy.
- Debian packages `acer-h340-usb-backup-dkms`, `h340-leds`, `h340-usb-backup` and `openmediavault-h340`, and a build tool that needs only Python 3.
- Install guide for systems without OpenMediaVault.
