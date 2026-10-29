#!/usr/bin/env python3
"""Build the H340 .deb packages with the standard library only.

Usage: python -B tools/build_plugin.py [--version 0.5.0] [--out DIR] [--only NAME]

Packages:
  openmediavault-h340         OMV plugin: settings pages for everything below
  h340-usb-backup             one-touch USB copy service (no OMV needed)
  h340-leds                   front panel lamp service
  acer-h340-usb-backup-dkms   USB Backup button kernel module (DKMS)

Each package is a source tree plus files taken from src/ or kernel/. Nothing
is installed by this tool.
"""
import argparse
import hashlib
import io
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
MAINTAINER_SCRIPTS = ("postinst", "prerm", "postrm", "triggers")
EXECUTABLE_SUFFIXES = (".py", ".sh")
EPOCH = 1793000000  # fixed so equal inputs give equal packages
# Salt notices a changed state file or template by its mtime, so a new version
# must carry newer mtimes. They grow with the version, one minute per step.
_mtime = [EPOCH]


def version_mtime(version):
    try:
        major, minor, patch = (int(part) for part in version.split("."))
    except ValueError:
        return EPOCH
    return EPOCH + 60 * (major * 10000 + minor * 100 + patch)

PACKAGES = {
    "openmediavault-h340": {
        "tree": "omv-plugin/openmediavault-h340",
        "extra": {},
        "conffiles": [],
    },
    "h340-usb-backup": {
        "tree": "packaging/h340-usb-backup",
        "extra": {
            "usr/lib/h340-usb-backup/h340_usb_copy.py": "src/backup/h340_usb_copy.py",
            "usr/lib/h340-usb-backup/h340_usb_runner.py": "src/backup/h340_usb_runner.py",
        },
        "conffiles": [],
    },
    "h340-leds": {
        "tree": "packaging/h340-leds",
        "extra": {
            "usr/lib/h340-leds/h340_leds.py": "src/leds/h340_leds.py",
            "usr/lib/h340-leds/h340_health.py": "src/leds/h340_health.py",
            "usr/lib/h340-leds/h340_sensors.py": "src/leds/h340_sensors.py",
            "usr/lib/h340-leds/h340_usb_copy.py": "src/backup/h340_usb_copy.py",
        },
        "conffiles": [],
    },
    "acer-h340-usb-backup-dkms": {
        "tree": "packaging/acer-h340-usb-backup-dkms",
        "extra": {
            "usr/src/acer-h340-usb-backup-1.0/acer_h340_usb_backup.c": "kernel/usb-backup/acer_h340_usb_backup.c",
            "usr/src/acer-h340-usb-backup-1.0/Makefile": "kernel/usb-backup/Makefile",
            "usr/src/acer-h340-usb-backup-1.0/dkms.conf": "kernel/usb-backup/dkms.conf",
            "etc/modules-load.d/acer-h340-usb-backup.conf": "kernel/usb-backup/acer-h340-usb-backup.conf",
        },
        "conffiles": ["/etc/modules-load.d/acer-h340-usb-backup.conf"],
    },
}


def payload(spec):
    """Return {archive path: bytes} for everything installed on the system."""
    tree = ROOT / spec["tree"]
    files = {}
    for path in sorted(tree.rglob("*")):
        relative = path.relative_to(tree).as_posix()
        if path.is_dir() or relative.startswith("debian/"):
            continue
        files[relative] = path.read_bytes()
    for target, source in spec["extra"].items():
        files[target] = (ROOT / source).read_bytes()
    files["usr/share/doc/%s/copyright" % spec["name"]] = copyright_text(spec["name"])
    return files


def copyright_text(name):
    """Debian copyright file: the MIT terms and, for the module, its own license."""
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    text += "\nSources and credits: see NOTICE.md in the project repository.\n"
    if name == "acer-h340-usb-backup-dkms":
        text += ("\nThe module sources under /usr/src/acer-h340-usb-backup-1.0 are licensed under "
                 "GPL-2.0-only (see the SPDX line in acer_h340_usb_backup.c). The MIT terms above "
                 "cover the rest of this package. On Debian the full text is in "
                 "/usr/share/common-licenses/GPL-2.\n")
    return text.encode("utf-8")


def is_executable(name):
    return name.endswith(EXECUTABLE_SUFFIXES)


def add_file(archive, name, data, mode):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = mode
    info.mtime = _mtime[0]
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    archive.addfile(info, io.BytesIO(data))


def add_dir(archive, name):
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.mode = 0o755
    info.mtime = _mtime[0]
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    archive.addfile(info)


def xz_tar(entries):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:xz", format=tarfile.GNU_FORMAT) as archive:
        entries(archive)
    return buffer.getvalue()


def data_tar(files):
    def entries(archive):
        directories = set()
        for name in files:
            parts = name.split("/")[:-1]
            for i in range(1, len(parts) + 1):
                directories.add("/".join(parts[:i]))
        add_dir(archive, ".")
        for directory in sorted(directories):
            add_dir(archive, "./" + directory)
        for name, data in sorted(files.items()):
            add_file(archive, "./" + name, data, 0o755 if is_executable(name) else 0o644)
    return xz_tar(entries)


def control_tar(spec, files, version):
    tree = ROOT / spec["tree"]
    control = (tree / "debian" / "control").read_text(encoding="utf-8")
    size_kib = (sum(len(data) for data in files.values()) + 1023) // 1024
    control = control.replace("@VERSION@", version).rstrip("\n")
    control += "\nInstalled-Size: %d\n" % size_kib
    md5sums = "".join("%s  %s\n" % (hashlib.md5(data).hexdigest(), name)
                      for name, data in sorted(files.items()))

    def entries(archive):
        add_dir(archive, ".")
        add_file(archive, "./control", control.encode("utf-8"), 0o644)
        add_file(archive, "./md5sums", md5sums.encode("ascii"), 0o644)
        if spec["conffiles"]:
            add_file(archive, "./conffiles", "".join(c + "\n" for c in spec["conffiles"]).encode("ascii"), 0o644)
        for name in MAINTAINER_SCRIPTS:
            script = tree / "debian" / name
            if script.exists():
                add_file(archive, "./" + name, script.read_bytes(), 0o644 if name == "triggers" else 0o755)
    return xz_tar(entries)


def ar_member(name, data):
    header = "%-16s%-12d%-6d%-6d%-8s%-10d`\n" % (name, _mtime[0], 0, 0, "100644", len(data))
    assert len(header) == 60
    member = header.encode("ascii") + data
    return member + (b"\n" if len(data) % 2 else b"")


def build(version, name="openmediavault-h340"):
    spec = dict(PACKAGES[name], name=name)
    _mtime[0] = version_mtime(version)
    files = payload(spec)
    return (b"!<arch>\n" + ar_member("debian-binary", b"2.0\n")
            + ar_member("control.tar.xz", control_tar(spec, files, version))
            + ar_member("data.tar.xz", data_tar(files)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="0.5.0")
    parser.add_argument("--out", default=str(ROOT / "dist"))
    parser.add_argument("--only", choices=sorted(PACKAGES))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name in ([args.only] if args.only else sorted(PACKAGES)):
        target = out / ("%s_%s_all.deb" % (name, args.version))
        target.write_bytes(build(args.version, name))
        print(target.name, hashlib.sha256(target.read_bytes()).hexdigest())


if __name__ == "__main__":
    sys.exit(main())
