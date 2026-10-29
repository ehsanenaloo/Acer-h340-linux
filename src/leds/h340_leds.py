#!/usr/bin/python3
"""Restricted H340 LEDs.

Register mapping: amd989/mediasmartserverd at commit
1d14c639213816a3b1f369cce54f07716630c991 (led_acerh340.h).
This is an independent, restricted implementation, not the upstream daemon.
"""

import fcntl
import argparse
import json
import logging
import os
from pathlib import Path
import signal
import struct
import threading
import time

from h340_health import KnownDisks, Observer, indication, load_config, purple_bays
from h340_usb_copy import read_backup_state, read_last_run_signal
from h340_sensors import read_sensors


LOG = logging.getLogger("h340-leds")
BACKUP_STATE = "/run/h340-usb-backup/state.json"
KNOWN_DISKS = "/var/lib/h340-leds/known-disks.json"
LAST_RUN = "/var/lib/h340-usb-backup/last-run.json"
TICK = 0.2  # the sampling step; every pattern below is a multiple of it
BAY_STATUS = "/run/h340-leds/status.json"
OWNED_BITS = {0x084B: 0x12, 0x084F: 0xCF, 0x118E: 0x10,
              0x118F: 0x09, 0x119A: 0x10, 0x119B: 0x09}
BLUE_BITS = ((0x084F, 0x40), (0x084F, 0x04), (0x084F, 0x01), (0x084B, 0x10))
RED_BITS = ((0x084F, 0x80), (0x084F, 0x08), (0x084F, 0x02), (0x084B, 0x02))


class Ports:
    def __enter__(self):
        self.fd = os.open("/dev/port", os.O_RDWR | os.O_CLOEXEC)
        return self

    def __exit__(self, *args):
        os.close(self.fd)

    def read(self, port):
        data = os.pread(self.fd, 1, port)
        if len(data) != 1:
            raise OSError("Short read at port 0x%04x" % port)
        return data[0]

    def write(self, port, value):
        if os.pwrite(self.fd, bytes([value]), port) != 1:
            raise OSError("Short write at port 0x%04x" % port)


def verify_platform(root=Path("/sys")):
    dmi = root / "class/dmi/id"
    if ((dmi / "sys_vendor").read_text().strip(),
            (dmi / "product_name").read_text().strip()) != ("Acer", "Aspire easyStore H340"):
        raise RuntimeError("Unsupported DMI identity")
    for module in ("dme1737", "gpio_ich", "leds_ss4200"):
        if (root / "module" / module).exists():
            raise RuntimeError("Potentially competing hardware driver: " + module)
    with (root / "bus/pci/devices/0000:00:1f.0/config").open("rb", buffering=0) as config:
        device = struct.unpack("<I", config.read(4))[0]
        config.seek(0x48)
        base = struct.unpack("<I", config.read(4))[0]
    if device != 0x27B88086 or base != 0x1181:
        raise RuntimeError("LPC identity or GPIO base differs from verified machine")


def verify_superio(io):
    """Read identity/base, restoring the LDN selector even on failure."""
    previous = None

    def config_read(index):
        io.write(0x2E, index)
        return io.read(0x2F)

    try:
        io.write(0x2E, 0x55)
        if config_read(0x20) != 0x86:
            raise RuntimeError("Unexpected Super I/O identity")
        previous = config_read(0x07)
        io.write(0x2E, 0x07)
        io.write(0x2F, 0x0A)
        base = (config_read(0x60) << 8) | config_read(0x61)
        if base != 0x0800:
            raise RuntimeError("Runtime base differs from verified machine")
    finally:
        try:
            if previous is not None:
                io.write(0x2E, 0x07)
                io.write(0x2F, previous)
                if config_read(0x07) != previous:
                    raise RuntimeError("Logical-device selector restoration failed")
        finally:
            io.write(0x2E, 0xAA)


def verify_usb_output(io):
    """Reject a changed pin configuration without initializing hardware."""
    use = sum(io.read(0x1180 + i) << (8 * i) for i in range(4))
    direction = sum(io.read(0x1184 + i) << (8 * i) for i in range(4))
    if not use & (1 << 27) or direction & (1 << 27):
        raise RuntimeError("USB GPIO27 is not an existing GPIO output")


class Lights:
    def __init__(self, io, usb_active_low):
        if type(usb_active_low) is not bool:
            raise ValueError("USB LED polarity must be explicitly configured")
        self.io = io
        self.usb_active_low = usb_active_low
        self.saved = {port: io.read(port) for port in OWNED_BITS}

    def masked_write(self, port, value):
        mask = OWNED_BITS[port]
        before = self.io.read(port)
        desired = (before & ~mask) | (value & mask)
        if before != desired:
            self.io.write(port, desired)
        if self.io.read(port) & mask != desired & mask:
            raise RuntimeError("LED readback mismatch at 0x%04x" % port)

    def apply(self, blue, red, system, usb_connected, purple=frozenset()):
        if type(usb_connected) is not bool:
            raise ValueError("Invalid USB presence observation")
        if not blue <= {0, 1, 2, 3} or not red <= {0, 1, 2, 3}:
            raise ValueError("Invalid bay index")
        if blue & red or system not in {"off", "blue", "blue-blink", "red"}:
            raise ValueError("Invalid indication")
        if not purple <= {0, 1, 2, 3} or purple & (blue | red):
            raise ValueError("Invalid purple bays")
        values = {0x084B: 0, 0x084F: 0}
        # Purple is both channels of a bay lit together.
        for bays, mapping in ((blue | purple, BLUE_BITS), (red | purple, RED_BITS)):
            for bay in bays:
                port, mask = mapping[bay]
                values[port] |= mask
        for port, value in values.items():
            self.masked_write(port, value)
        # Both system colors are active low. Only source-mapped bits are owned.
        self.masked_write(0x119A, 0x10 if system == "blue-blink" else 0)
        self.masked_write(0x119B, 0)
        self.masked_write(0x118E, 0 if system in {"blue", "blue-blink"} else 0x10)
        usb_level = 0x08 if usb_connected != self.usb_active_low else 0
        self.masked_write(0x118F, (0 if system == "red" else 1) | usb_level)

    def restore(self):
        failures = []
        # Restore level before blink; attempt every bank even if one fails.
        for port in (0x084B, 0x084F, 0x118E, 0x118F, 0x119A, 0x119B):
            try:
                self.masked_write(port, self.saved[port])
            except Exception as exc:
                failures.append("0x%04x: %s" % (port, exc))
        if failures:
            raise RuntimeError("LED restoration failed: " + "; ".join(failures))


def usb_signal(snapshot, now):
    """Level of the front USB lamp. It has one blue LED, so meaning is a pattern.

    steady: device connected. slow blink: copying. three quick pulses, then a
    pause: copy verified and the device unmounted, safe to remove (one minute).
    fast blink: the copy did not complete (one minute). Off: no device.
    """
    if not snapshot["usb_connected"]:
        return False
    step = int(now / TICK)
    if snapshot.get("usb_backup") == "copying":
        return int(now * 2) % 2 == 0
    last = snapshot.get("usb_last")
    if last == "done":
        return step % 10 in (0, 2, 4)
    if last == "error":
        return step % 2 == 0
    return True


def write_bay_status(path, bays):
    """Publish what the service sees per bay, for the settings pages."""
    data = {"bays": {str(bay): info for bay, info in sorted(bays.items())}}
    temporary = Path(path + ".tmp")
    temporary.write_text(json.dumps(data), encoding="utf-8")
    os.replace(temporary, path)


def run(io, stop, observe, usb_active_low, publish=None):
    lights = Lights(io, usb_active_low)
    last = None
    last_bays = None
    try:
        while not stop.is_set():
            snapshot = observe()
            if stop.is_set():
                break
            blue, red, system = indication(snapshot, int(time.monotonic() * 2) % 2 == 0)
            # Connected is not copied: the lamp changes only for a live copy
            # and for a recent finished copy, see usb_signal.
            usb_lamp = usb_signal(snapshot, time.monotonic())
            purple = purple_bays(snapshot)
            lights.apply(blue - purple, red - purple, system, usb_lamp, purple)
            bays = snapshot.get("bays")
            if publish is not None and bays is not None and bays != last_bays:
                try:
                    publish(bays)
                    last_bays = bays
                except OSError as exc:
                    LOG.error("Could not publish the bay status: %s", exc)
            status = (snapshot["system"], snapshot["cpu_critical"],
                      snapshot["hardware"]["fan_healthy"],
                      snapshot["usb_connected"],
                      tuple(sorted((bay, d["present"], d["health"], d.get("configured"))
                                   for bay, d in snapshot["disks"].items())))
            if status != last:
                LOG.info("Observed system/cpu-critical/fan/USB-presence/disk health: %s", status)
                last = status
            stop.wait(0.2)
    finally:
        # Let restoration finish before another ordinary stop signal arrives.
        old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT})
        try:
            lights.restore()
            LOG.info("Startup LED bits restored and verified")
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="/etc/h340-leds.json")
    parser.add_argument("--check", action="store_true", help="Read observations without opening hardware ports")
    args = parser.parse_args()
    seed = load_config(args.config)
    config = json.loads(Path(args.config).read_text())
    fan_input = config["fan_tach_input"]
    usb_active_low = config["usb_led_active_low"]
    if type(usb_active_low) is not bool:
        raise ValueError("Invalid configured USB LED polarity")
    if type(fan_input) is not int or fan_input not in (1, 2, 3):
        raise ValueError("Invalid configured fan input")
    verify_platform()
    # The check run only observes: it must not remember disks.
    known = KnownDisks(KNOWN_DISKS, seed=seed, log=LOG.warning,
                       persist=not args.check)
    observer = Observer(known, backup=lambda: read_backup_state(BACKUP_STATE),
                        last_run=lambda: read_last_run_signal(LAST_RUN))
    if args.check:
        print(json.dumps(observer.sample(), indent=2))
        return
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda signum, frame: stop.set())
    # The lock covers Super I/O access as well as the runtime LED loop.
    with open("/run/h340-leds/lock", "a", encoding="ascii") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        verify_platform()
        with Ports() as io:
            verify_superio(io)
            # GPIO27 was already an output during calibration; never initialize it.
            verify_usb_output(io)
            observer.hardware = lambda: read_sensors(io, fan_input)
            run(io, stop, observer.sample, usb_active_low,
                lambda bays: write_bay_status(BAY_STATUS, bays))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        LOG.exception("LED service stopped with an error")
        raise SystemExit(1)
