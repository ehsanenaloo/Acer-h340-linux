#!/usr/bin/python3
"""USB Backup button runner for the H340.

Waits for the KEY_COPY press from the "Acer H340 USB Backup" input device,
mounts the single front-port filesystem read-only, runs the verified copy
engine into a new run directory and unmounts. One copy at a time; a press
during a copy is ignored. Nothing is deleted or overwritten.
"""
import argparse
import json
import logging
import os
from pathlib import Path
import posixpath
import re
import select
import signal
import struct
import subprocess
import threading
import time

from h340_usb_copy import StatusFile, run_copy

LOG = logging.getLogger("h340-usb-backup")
KEY_COPY = 133
EV_KEY = 1
EVENT = struct.Struct("llHHi")
INPUT_NAME = "Acer H340 USB Backup"
FRONT_ROUTE = re.compile(r"/0000:00:1d\.7/usb\d+/\d+-5/\d+-5:1\.0/host\d+/")
MOUNT_POINT = "/run/h340-usb-backup/source"
STATE_PATH = "/run/h340-usb-backup/state.json"
LAST_RUN_PATH = "/var/lib/h340-usb-backup/last-run.json"
MOUNT_OPTIONS = "ro,nosuid,nodev,noexec"


class Refused(Exception):
    pass


def load_config(path):
    """Return (destination_root, reserve_bytes, label, exclude patterns).

    label and exclude are optional so the first installed configuration stays
    valid. Patterns match one file or directory name, never a path.
    """
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    root, reserve = config["destination_root"], config["reserve_bytes"]
    if type(root) is not str or not posixpath.isabs(root):
        raise ValueError("destination_root must be an absolute path")
    if posixpath.normpath(root) != root.rstrip("/") and root != "/" or ".." in root.split("/"):
        raise ValueError("destination_root must be a normalized path")
    if type(reserve) is not int or type(reserve) is bool or reserve < 0:
        raise ValueError("reserve_bytes must be a non-negative integer")
    label = config.get("label", "usb")
    if type(label) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", label):
        raise ValueError("label must be 1-32 letters, digits, - or _")
    exclude = config.get("exclude", [])
    if (type(exclude) is not list or len(exclude) > 100
            or any(type(p) is not str or not p or "/" in p or len(p) > 255 for p in exclude)):
        raise ValueError("exclude must be a list of name patterns")
    return root, reserve, label, exclude


def find_input_event(root=Path("/sys/class/input")):
    for entry in sorted(root.glob("event*")):
        try:
            if (entry / "device/name").read_text().strip() == INPUT_NAME:
                return "/dev/input/" + entry.name
        except OSError:
            continue
    return None


def find_front_device(root=Path("/sys/class/block")):
    """Return the one device node on the verified front route, or refuse."""
    disks = []
    for block in root.iterdir():
        if (block / "partition").exists():
            continue
        try:
            actual = str(block.resolve(strict=True))
        except FileNotFoundError:
            continue
        if FRONT_ROUTE.search(actual):
            disks.append(block)
    if len(disks) != 1:
        raise Refused("Expected exactly one front USB disk, found %d" % len(disks))
    parts = sorted(p.name for p in disks[0].iterdir()
                   if p.name.startswith(disks[0].name) and (p / "partition").exists())
    if len(parts) > 1:
        raise Refused("Front USB disk has several partitions")
    return "/dev/" + (parts[0] if parts else disks[0].name)


def is_mounted(path):
    result = subprocess.run(["/usr/bin/findmnt", "-n", "--target", path, "-o", "TARGET"],
                            capture_output=True, text=True, timeout=10, check=False)
    return result.stdout.strip() == path


def mount_readonly(device, target):
    Path(target).mkdir(parents=True, exist_ok=True)
    if is_mounted(target):
        raise Refused("Mount point already in use")
    result = subprocess.run(["/usr/bin/mount", "-o", MOUNT_OPTIONS, device, target],
                            capture_output=True, text=True, timeout=60, check=False)
    if result.returncode:
        raise Refused("Mount failed: " + result.stderr.strip()[:200])


def unmount(target):
    result = subprocess.run(["/usr/bin/umount", target], capture_output=True,
                            text=True, timeout=60, check=False)
    if result.returncode:
        raise OSError("Unmount failed: " + result.stderr.strip()[:200])


def record_last_run(path, result, clock=time.time):
    """Keep the outcome of the latest copy across restarts and reboots."""
    data = {"finished": int(clock()), "ok": bool(result["ok"]),
            "copied": result.get("copied", 0), "total": result.get("total", 0),
            "skipped": len(result.get("skipped", [])), "excluded": result.get("excluded", 0),
            "run_dir": result.get("run_dir"), "error": result.get("error")}
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(data), encoding="utf-8")
    os.replace(temporary, target)


def free_space_of(path):
    stat = os.statvfs(path)
    return stat.f_bavail * stat.f_frsize


class Runner:
    def __init__(self, destination_root, reserve, status, stop,
                 label="usb", exclude=(), find_device=find_front_device, mount=mount_readonly,
                 umount=unmount, copy=run_copy, mount_point=MOUNT_POINT,
                 free_space=free_space_of, makedirs=os.makedirs, history=record_last_run,
                 history_path=LAST_RUN_PATH):
        self.destination_root = destination_root
        self.reserve = reserve
        self.label = label
        self.exclude = tuple(exclude)
        self.status = status
        self.stop = stop
        self.find_device = find_device
        self.mount = mount
        self.umount = umount
        self.copy = copy
        self.mount_point = mount_point
        self.free_space = free_space
        self.makedirs = makedirs
        self.history = history
        self.history_path = history_path
        self.busy = threading.Lock()

    def press(self):
        """Handle one button press. Returns the copy result, or None if ignored."""
        if not self.busy.acquire(blocking=False):
            LOG.info("Press ignored: a copy is already running")
            return None
        try:
            return self._copy_once()
        finally:
            self.busy.release()

    def _copy_once(self):
        mounted = False
        try:
            device = self.find_device()
            self.makedirs(self.destination_root, mode=0o755, exist_ok=True)
            self.mount(device, self.mount_point)
            mounted = True
            LOG.info("Copy started from %s", device)
            result = self.copy(
                self.mount_point, self.destination_root, self.label, self.status,
                lambda: self.free_space(self.destination_root), self.reserve,
                stop=self.stop.is_set, exclude=self.exclude)
        except Refused as exc:
            LOG.error("Copy refused: %s", exc)
            result = {"ok": False, "error": str(exc), "skipped": []}
            self.status.write("failed", error=str(exc))
        except Exception as exc:
            LOG.exception("Copy failed")
            result = {"ok": False, "error": str(exc)[:200], "skipped": []}
            self.status.write("failed", error=result["error"])
        if mounted:
            try:
                self.umount(self.mount_point)
            except OSError as exc:
                LOG.error("%s", exc)
                result = {"ok": False, "error": str(exc), "skipped": []}
                self.status.write("failed", error=str(exc))
        try:
            self.history(self.history_path, result)
        except OSError as exc:
            LOG.error("Could not record the result: %s", exc)
        if result["ok"]:
            LOG.info("Copy verified: %d files in %s", result["copied"], result["run_dir"])
        else:
            LOG.error("Copy not complete: %s", result["error"])
        if result["skipped"]:
            LOG.warning("Skipped non-regular entries: %d", len(result["skipped"]))
        return result


def parse_events(data):
    """Yield True for each KEY_COPY press in a buffer of input_event records."""
    for offset in range(0, len(data) - EVENT.size + 1, EVENT.size):
        _, _, kind, code, value = EVENT.unpack_from(data, offset)
        if kind == EV_KEY and code == KEY_COPY and value == 1:
            yield True


def wait_for_input(find, stop, interval=5.0):
    """Wait for the button device instead of exiting.

    The module may load after the service starts, or be missing on a kernel it
    was not built for. Exiting would leave the unit failed with no way back
    when the module appears; waiting costs nothing and the status page shows
    the button as missing.
    """
    announced = False
    while not stop.is_set():
        device = find()
        if device is not None:
            return device
        if not announced:
            LOG.warning("Input device not found: %s. Waiting for the kernel module.", INPUT_NAME)
            announced = True
        stop.wait(interval)
    return None


def listen(device, runner, stop):
    fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        while not stop.is_set():
            ready, _, _ = select.select([fd], [], [], 1.0)
            if not ready:
                continue
            try:
                data = os.read(fd, EVENT.size * 16)
            except BlockingIOError:
                continue
            for _ in parse_events(data):
                runner.press()
    finally:
        os.close(fd)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="/etc/h340-usb-backup.json")
    args = parser.parse_args()
    root, reserve, label, exclude = load_config(args.config)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda signum, frame: stop.set())
    device = wait_for_input(find_input_event, stop)
    if device is None:
        return
    runner = Runner(root, reserve, StatusFile(STATE_PATH), stop, label, exclude)
    LOG.info("Waiting for the USB Backup button on %s", device)
    listen(device, runner, stop)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        LOG.exception("USB backup runner stopped with an error")
        raise SystemExit(1)
