#!/usr/bin/python3
"""Non-destructive copy engine for the H340 USB Backup workflow.

The engine only reads the source tree and only creates new files below a new
run directory. It never mounts, deletes, overwrites or follows symlinks. The
caller decides when a copy may start; this module is not a trigger.
"""
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import time

CHUNK = 1 << 20
STATE_MAX_AGE = 30.0


class CopyAborted(Exception):
    pass


def file_digest(path, stop=None):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            if stop is not None and stop():
                raise CopyAborted("Interrupted")
            chunk = handle.read(CHUNK)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)


class StatusFile:
    """Atomic JSON status for the single LED process to read."""

    def __init__(self, path, clock=time.time):
        self.path = Path(path)
        self.clock = clock

    def write(self, state, **fields):
        data = dict(fields, state=state, pid=os.getpid(), updated=self.clock())
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps(data), encoding="ascii")
        os.replace(temporary, self.path)


def read_backup_state(path, clock=time.time, max_age=STATE_MAX_AGE):
    """Return copying/success/failed, or None when absent, invalid or stale.

    A copying record that stopped updating is not trusted: an LED must never
    blink for a copy that is no longer running.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="ascii"))
        state, updated = data["state"], float(data["updated"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if state not in {"copying", "success", "failed"}:
        return None
    if state == "copying" and clock() - updated > max_age:
        return None
    return state


def is_excluded(name, patterns):
    """Match one path component against user patterns, ignoring case."""
    name = name.casefold()
    return any(fnmatch.fnmatchcase(name, pattern.casefold()) for pattern in patterns)


def read_last_run_signal(path, clock=time.time, window=60.0):
    """Return "done" or "error" for a copy that finished within the window.

    The runner writes this record after it has unmounted the device, so "done"
    means the device can be removed. Older or unreadable records give None.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        age = clock() - float(data["finished"])
        ok = bool(data["ok"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if age < 0 or age > window:
        return None
    return "done" if ok else "error"


def scan(source, tick=None, exclude=()):
    """Return (regular files, skipped non-regular names, excluded count).

    Excluded names are user choices, so they are counted apart from skipped
    entries and never make a run incomplete.
    """
    source = Path(source)
    files, skipped, excluded = [], [], 0
    for root, dirs, names in os.walk(source, followlinks=False):
        if tick is not None:
            tick()
        kept = [name for name in dirs if not is_excluded(name, exclude)]
        excluded += len(dirs) - len(kept)
        dirs[:] = sorted(kept)
        for name in sorted(names):
            if is_excluded(name, exclude):
                excluded += 1
                continue
            path = Path(root) / name
            relative = path.relative_to(source)
            if path.is_symlink() or not path.is_file():
                skipped.append(str(relative))
            else:
                files.append(relative)
        for name in list(dirs):
            if (Path(root) / name).is_symlink():
                dirs.remove(name)
                skipped.append(str((Path(root) / name).relative_to(source)))
    return files, skipped, excluded


def _inside(child, parent):
    child, parent = Path(os.path.realpath(child)), Path(os.path.realpath(parent))
    return child == parent or parent in child.parents


def copy_one(source_file, target, stop=None):
    """Copy to a new name, verify by re-reading both sides, then publish."""
    before = os.stat(source_file)
    partial = target.with_name(target.name + ".part")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        digest = hashlib.sha256()
        # 'xb' refuses an existing partial name instead of replacing it.
        with open(source_file, "rb") as src, open(partial, "xb") as dst:
            while True:
                if stop is not None and stop():
                    raise CopyAborted("Interrupted")
                chunk = src.read(CHUNK)
                if not chunk:
                    break
                digest.update(chunk)
                dst.write(chunk)
            dst.flush()
            os.fsync(dst.fileno())
        if file_digest(partial, stop) != digest.hexdigest():
            raise OSError("Verification failed")
        after = os.stat(source_file)
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise OSError("Source changed during copy")
        os.utime(partial, ns=(before.st_atime_ns, before.st_mtime_ns))
        if os.path.lexists(target):
            raise FileExistsError(str(target))
        os.rename(partial, target)
    except BaseException:
        try:
            os.unlink(partial)
        except OSError:
            pass
        raise
    return before.st_size


def run_copy(source, destination_root, label, status, free_space, reserve,
             stop=None, clock=time.gmtime, exclude=()):
    """Copy every regular file from source into a new run directory.

    Returns a result dict. Success is reported only when every regular file was
    copied and verified; skipped symlinks/special files are listed but never
    count as copied. Nothing is ever removed from either side.
    """
    source, destination_root = Path(source), Path(destination_root)
    if not source.is_dir() or not destination_root.is_dir():
        raise ValueError("Source and destination root must be existing directories")
    if _inside(destination_root, source) or _inside(source, destination_root):
        raise ValueError("Source and destination must not contain each other")
    if not label.replace("-", "").replace("_", "").isalnum():
        raise ValueError("Invalid label")
    run_dir = destination_root / (time.strftime("%Y%m%dT%H%M%SZ", clock()) + "-" + label)
    progress = {"copied": 0, "total": 0}
    last_beat = [-float("inf")]

    def beat():
        # Keeps the record fresh during the scan and inside very large files.
        now = time.monotonic()
        if now - last_beat[0] >= 2.0:
            last_beat[0] = now
            status.write("copying", **progress)

    def guard():
        beat()
        return stop() if stop is not None else False

    status.write("copying", **progress)
    files, skipped, excluded = scan(source, beat, exclude)
    progress["total"] = len(files)
    total = 0
    for name in files:
        beat()
        total += os.stat(source / name).st_size
    if total + reserve > free_space():
        result = {"ok": False, "error": "Not enough free space", "copied": 0,
                  "total": len(files), "skipped": skipped, "excluded": excluded,
                  "run_dir": None}
        status.write("failed", error=result["error"])
        return result
    run_dir.mkdir()  # Fails if the run already exists; never merges into old runs.
    copied, errors = 0, []
    status.write("copying", copied=0, total=len(files))
    try:
        for name in files:
            try:
                copy_one(source / name, run_dir / name, guard)
                copied += 1
                progress["copied"] = copied
            except CopyAborted:
                raise
            except OSError as exc:
                errors.append("%s: %s" % (name, exc))
    except CopyAborted:
        status.write("failed", error="Interrupted", copied=copied, total=len(files))
        return {"ok": False, "error": "Interrupted", "copied": copied,
                "total": len(files), "skipped": skipped, "excluded": excluded,
                "run_dir": str(run_dir)}
    ok = not errors and copied == len(files)
    result = {"ok": ok, "error": None if ok else "; ".join(errors[:5]),
              "copied": copied, "total": len(files), "skipped": skipped,
              "excluded": excluded, "run_dir": str(run_dir)}
    status.write("success" if ok else "failed", copied=copied, total=len(files),
                 error=result["error"])
    return result
