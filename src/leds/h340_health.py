#!/usr/bin/python3
"""Read-only Debian observations for the restricted H340 LED controller."""
import json
import os
from pathlib import Path
import re
import subprocess
import time


def smart_health(result):
    """Return None for unavailable data, never a fabricated failure/pass."""
    try:
        data = json.loads(result.stdout)
    except (ValueError, TypeError):
        return None
    if result.returncode & 7:
        return None
    passed = data.get("smart_status", {}).get("passed")
    if not isinstance(passed, bool):
        return None
    if not passed or result.returncode & 0x18:
        return False
    table = data.get("ata_smart_attributes", {}).get("table")
    if not isinstance(table, list):
        return None
    if not {197, 198} <= {attribute.get("id") for attribute in table}:
        return None
    for attribute in table:
        if attribute.get("id") in (197, 198):
            value = attribute.get("raw", {}).get("value")
            if not isinstance(value, int):
                return None
            if value > 0:
                return False
    return True


def read_smart(device):
    try:
        result = subprocess.run(
            ["/usr/sbin/smartctl", "-j", "-d", "ata", "-n", "standby,3,5",
             "-H", "-A", device], capture_output=True, text=True,
            timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return smart_health(result)


def read_system():
    result = subprocess.run(["/usr/bin/systemctl", "is-system-running"],
                            capture_output=True, text=True, timeout=5, check=False)
    state = result.stdout.strip()
    if state not in {"running", "degraded", "starting", "initializing", "stopping",
                     "maintenance", "offline"}:
        state = "unknown"
    flags = []
    for sensor in Path("/sys/class/hwmon").glob("hwmon*"):
        for alarm in sensor.glob("temp*_crit_alarm"):
            flags.append(int(alarm.read_text().strip()))
    return state, (any(flags) if flags else None)


def load_config(path):
    """Return the optional legacy disk list as {identity: bay}.

    New installations leave it out: the bay of a disk comes from its SATA port
    and the service learns which disks belong to the server. A list that is
    present only seeds that memory the first time.
    """
    config = json.loads(Path(path).read_text())
    devices = config.get("expected_disks", {})
    if not isinstance(devices, dict):
        raise ValueError("Invalid expected disk configuration")
    bays = []
    for identity, bay in devices.items():
        if not re.fullmatch(r"ata-[A-Za-z0-9_.-]+", identity):
            raise ValueError("Invalid ATA by-id name")
        if type(bay) is not int or bay not in range(4):
            raise ValueError("Invalid bay index")
        bays.append(bay)
    if len(set(bays)) != len(bays):
        raise ValueError("Duplicate expected bay")
    return devices


def discover_disks():
    disks = {}
    for block in Path("/sys/class/block").iterdir():
        if (block / "partition").exists():
            continue
        try:
            actual = str(block.resolve(strict=True))
        except FileNotFoundError:
            continue  # Device was removed during enumeration, not a healthy disk.
        match = re.search(r"/0000:00:1f\.2/ata([1-4])/host\d+/", actual)
        if match:
            disks[block.name] = int(match[1]) - 1
    return disks


def front_usb_connected(root=Path("/sys/class/block")):
    """Presence only on the physically verified direct EHCI front-port route."""
    for block in root.iterdir():
        if (block / "partition").exists():
            continue
        try:
            actual = str(block.resolve(strict=True))
        except FileNotFoundError:
            continue
        if re.search(r"/0000:00:1d\.7/usb\d+/\d+-5/\d+-5:1\.0/host\d+/", actual):
            return True
    return False


def read_identities(by_id=Path("/dev/disk/by-id")):
    """Return {device name: ata by-id name} for whole SATA disks."""
    result = {}
    try:
        entries = sorted(by_id.iterdir(), key=lambda entry: entry.name)
    except OSError:
        return result
    for entry in entries:
        name = entry.name
        if not re.fullmatch(r"ata-[A-Za-z0-9_.-]+", name) or re.search(r"-part\d+$", name):
            continue
        try:
            result[entry.resolve(strict=True).name] = name
        except OSError:
            continue
    return result


def mounted_disks(mounts=Path("/proc/mounts")):
    """Names of SATA disks that have a mounted filesystem."""
    disks = set()
    try:
        text = mounts.read_text()
    except OSError:
        return disks
    for line in text.splitlines():
        match = re.match(r"/dev/(sd[a-z]+)\d*\s", line)
        if match:
            disks.add(match[1])
    return disks


class KnownDisks:
    """Which disk belongs to which bay, kept across restarts.

    A disk is added when it has a mounted filesystem, which is how the system
    takes a disk into use. Nothing is ever written to a disk.
    """

    def __init__(self, path, seed=None, log=None, persist=True):
        self.path = Path(path)
        self.persist = persist
        self.bays = {}
        try:
            data = json.loads(self.path.read_text())
            for bay, identity in data["bays"].items():
                if (int(bay) in range(4) and isinstance(identity, str)
                        and re.fullmatch(r"ata-[A-Za-z0-9_.-]+", identity)):
                    self.bays[int(bay)] = identity
        except FileNotFoundError:
            self.bays = {bay: identity for identity, bay in (seed or {}).items()}
            if self.bays:
                self.save()
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            if log:
                log("Known disk list unreadable, starting empty: %s" % exc)
            self.bays = {}

    def save(self):
        if not self.persist:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps({"bays": {str(b): i for b, i in sorted(self.bays.items())}}))
        os.replace(temporary, self.path)

    def get(self, bay):
        return self.bays.get(bay)

    def set(self, bay, identity):
        if self.bays.get(bay) != identity:
            self.bays[bay] = identity
            self.save()

    def forget(self, bays):
        changed = False
        for bay in bays:
            changed = self.bays.pop(bay, None) is not None or changed
        if changed:
            self.save()


FORGET_REQUEST = "/run/h340-leds/forget-missing"


def take_forget_request(path=FORGET_REQUEST):
    """True once when the settings page asked to forget removed disks."""
    try:
        os.unlink(path)
    except OSError:
        return False
    return True


class Observer:
    def __init__(self, known, smart=read_smart, system=read_system,
                 discover=discover_disks, clock=time.monotonic, hardware=None,
                 usb=front_usb_connected, backup=None, identify=read_identities,
                 mounted=mounted_disks, forget_request=take_forget_request,
                 last_run=None):
        self.known = known
        self.smart = smart
        self.system = system
        self.discover = discover
        self.clock = clock
        self.last_system = -float("inf")
        self.system_value = ("unknown", None)
        self.hardware = hardware
        self.usb = usb
        self.backup = backup
        self.last_run = last_run
        self.identify = identify
        self.mounted = mounted
        self.forget_request = forget_request
        self.hardware_value = {"fan_healthy": None}
        self.identities = {}
        self.mounted_value = set()
        self.last_identity = -float("inf")
        self.last_names = frozenset()
        self.cache = {}
        self.stats = {}

    def sample(self):
        now = self.clock()
        disks = self.discover()
        if now - self.last_system >= 5:
            self.system_value = self.system()
            self.hardware_value = self.hardware() if self.hardware is not None else {"fan_healthy": None}
            self.last_system = now
        # The identity and mount lists change slowly and cost a directory scan
        # each (the NAS has a 1.6 GHz Atom), so read them once a second or when
        # the set of disks changes. A swapped disk shows up as a missing and
        # then a new device name within that time.
        names = frozenset(disks)
        if now - self.last_identity >= 1.0 or names != self.last_names:
            self.identities = self.identify()
            self.mounted_value = self.mounted()
            self.last_identity = now
            self.last_names = names
        observations, bay_status = {}, {}
        present_bays = set(disks.values())
        if self.forget_request():
            self.known.forget([b for b in list(self.known.bays) if b not in present_bays])
        seen = set()
        for name, bay in disks.items():
            identity = self.identities.get(name)
            if identity is not None and name in self.mounted_value:
                self.known.set(bay, identity)
            if identity is None or self.known.get(bay) != identity:
                # A drive the server has not taken into use: observable, never
                # silently treated as healthy or as the bay's former disk.
                observations[bay] = {"present": True, "health": None, "activity": False,
                                     "configured": False}
                bay_status[bay] = {"identity": identity, "state": "new"}
                continue
            seen.add(identity)
            block = Path("/sys/class/block") / name
            state = (block / "device/state").read_text().strip()
            cached = self.cache.get(identity)
            if cached is None or now - cached[0] >= 300:
                cached = (now, self.smart("/dev/" + name))
                self.cache[identity] = cached
            values = list(map(int, (block / "stat").read_text().split()))
            counters = (values[0], values[4])
            previous = self.stats.get(identity)
            busy = values[8] > 0 or (previous is not None and counters != previous)
            self.stats[identity] = counters
            observations[bay] = {"present": True,
                                 "health": cached[1] if state == "running" else False,
                                 "activity": busy, "configured": True}
            bay_status[bay] = {"identity": identity, "state": "ok"}
        for bay, identity in sorted(self.known.bays.items()):
            if bay in observations:
                continue
            # Never reuse a former occupant's health after a disappearance.
            observations[bay] = {"present": False, "health": False, "activity": False,
                                 "configured": True}
            bay_status[bay] = {"identity": identity, "state": "missing"}
        for identity in list(self.cache):
            if identity not in seen:
                self.cache.pop(identity, None)
                self.stats.pop(identity, None)
        state, critical = self.system_value
        return {"disks": observations, "system": state, "cpu_critical": critical,
                "hardware": self.hardware_value, "usb_connected": self.usb(),
                "usb_backup": self.backup() if self.backup is not None else None,
                "usb_last": self.last_run() if self.last_run is not None else None,
                "bays": bay_status}


def purple_bays(snapshot):
    """Bays holding a drive that is not a configured expected identity.

    Debian adaptation of the manual's purple for storage that is not part of
    the server's storage. It says nothing about the drive's health.
    """
    return {bay for bay, disk in snapshot["disks"].items()
            if disk["present"] and disk.get("configured") is False}


def indication(snapshot, blink_on):
    blue, red = set(), set()
    for bay, disk in snapshot["disks"].items():
        if disk["health"] is False:
            if blink_on:
                red.add(bay)
        elif disk["present"] and disk["activity"]:
            blue.add(bay)
    fault = (snapshot["system"] in {"degraded", "maintenance"}
             or snapshot["cpu_critical"] is True
             or snapshot["hardware"]["fan_healthy"] is False
             or any(d["health"] is False for d in snapshot["disks"].values()))
    complete = (snapshot["cpu_critical"] is not None
                and snapshot["hardware"]["fan_healthy"] is True
                and all(d["health"] is True for d in snapshot["disks"].values()))
    if fault:
        system = "red"
    elif snapshot["system"] in {"starting", "initializing", "stopping"}:
        system = "blue-blink"
    elif snapshot["system"] == "running" and complete:
        system = "blue"
    else:
        system = "off"
    return blue, red, system


if __name__ == "__main__":
    import sys
    expected = load_config(sys.argv[1])
    print(json.dumps(Observer(expected).sample(), indent=2))
