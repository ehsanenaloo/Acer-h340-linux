# Install

Only the OpenMediaVault pages need OpenMediaVault. The rest works on any systemd system. Build the packages with `python3 tools/build_plugin.py` (Python 3 is all you need), or take the `.deb` files from a release.

| Package | What it does | Needs |
| --- | --- | --- |
| `acer-h340-usb-backup-dkms` | Makes the front USB Backup button a Linux key press | `dkms` and the headers of your running kernel |
| `h340-leds` | The front lamps | Python 3.11 or newer, `smartmontools`, systemd, `/dev/port` |
| `h340-usb-backup` | Copies the front USB device to a folder | Python 3.11 or newer, `mount`, systemd |
| `openmediavault-h340` | Settings pages for all of the above | OpenMediaVault 8.5.10 or newer |

The machine must be an Acer Aspire easyStore H340 with the WG945GCM board. The lamp service checks the board and will not start on another one. It also will not start while `dme1737`, `gpio_ich` or `leds_ss4200` is loaded.

## Debian and Ubuntu

```bash
sudo apt install ./acer-h340-usb-backup-dkms_*.deb ./h340-leds_*.deb ./h340-usb-backup_*.deb
```

DKMS builds the module for your running kernel and loads it at every boot. To load it now:

```bash
sudo modprobe acer_h340_usb_backup
grep -l "Acer H340 USB Backup" /sys/class/input/event*/device/name
```

The second command should print one path. That is the button.

### Lamps

Create `/etc/h340-leds.json`:

```json
{ "fan_tach_input": 1, "usb_led_active_low": true }
```

These two values were measured on the H340. Then start the service:

```bash
sudo systemctl enable --now h340-leds
```

You do not assign disks to bays. Each bay is a fixed SATA port, and the service remembers which disks belong to the machine. A disk joins the list when it is mounted. A disk that is not mounted shows purple.

The list is in `/var/lib/h340-leds/known-disks.json`. To forget a disk that you removed, stop the service, delete that bay from the file and start the service again.

### USB copy

Copy the example file and edit it:

```bash
sudo cp /usr/share/doc/h340-usb-backup/h340-usb-backup.json.example /etc/h340-usb-backup.json
sudo nano /etc/h340-usb-backup.json
```

| Key | Meaning |
| --- | --- |
| `destination_root` | An existing folder, given as a full path. Each run makes a dated folder inside it |
| `reserve_bytes` | A run is refused if it would leave less free space than this |
| `label` | Added to each dated folder name. Use letters, digits, `-` and `_` |
| `exclude` | File and folder names to skip. Each pattern matches one name, ignoring case. `*` and `?` work |

Start the service:

```bash
sudo systemctl enable --now h340-usb-backup
```

Plug in a device and press the button. The device is mounted read-only, nothing is deleted or overwritten, and every file is checked after it is copied. The result of the last run is in `/var/lib/h340-usb-backup/last-run.json`.

### Power button

The button is an ACPI power button handled by `systemd-logind`. To shut down on a short press:

```bash
sudo mkdir -p /etc/systemd/logind.conf.d
printf '[Login]\nHandlePowerKey=poweroff\n' | sudo tee /etc/systemd/logind.conf.d/90-power-button.conf
sudo systemctl kill -s HUP --kill-whom=main systemd-logind
```

Use `suspend` instead of `poweroff` for sleep. Sleep has not been tried on this model. Test it before you rely on it.

## OpenMediaVault

Install the same packages and `openmediavault-h340`:

```bash
sudo apt install ./h340-usb-backup_*.deb ./openmediavault-h340_*.deb
```

Then open **Services > H340 USB Backup**. The pages write the two settings files for you, start and stop the services, and use the power button setting that OpenMediaVault already has. On a fresh install the power button is set to shut down, but only if it was still on the OpenMediaVault default.

Use `apt install` for the upgrade, not `dpkg -i`, because the copy service moved from the plugin into its own package.

## Other systems

The files are plain scripts. Put `src/leds/*.py` and `src/backup/h340_usb_copy.py` in one folder for the lamp service. Put `src/backup/*.py` in another for the copy service. Use the unit files in `packaging/h340-leds` and `packaging/h340-usb-backup` and change the paths. Build the module from `kernel/usb-backup` with `make KERNEL_RELEASE=$(uname -r)` against the matching headers.

## Check

```bash
systemctl is-active h340-leds h340-usb-backup
```

Both should say `active`. If the copy service says `failed` and the log says the input device is missing, the module is not loaded for your kernel. Install the headers and run `sudo dkms autoinstall`.
