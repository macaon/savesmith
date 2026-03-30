"""Process discovery and /proc/pid/maps parsing."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Small script that runs on the host via flatpak-spawn.
# Searches all processes in a single invocation and returns JSON.
_SCRIPT_MARKER = "__savesmith_proc_scan__"
_FIND_PROCS_SCRIPT = r'''
import json, os, sys
needle = sys.argv[1].lower()
own_pid = os.getpid()
results = []
for entry in os.listdir("/proc"):
    if not entry.isdigit():
        continue
    pid = int(entry)
    if pid == own_pid:
        continue
    try:
        with open(f"/proc/{entry}/cmdline", "rb") as f:
            cmdline = f.read()
        if b"__savesmith_proc_scan__" in cmdline:
            continue
        cmdline_str = cmdline.replace(b"\x00", b" ").decode("utf-8", "replace").strip()
        with open(f"/proc/{entry}/comm") as f:
            comm = f.read().strip()
        if needle in comm.lower() or needle in cmdline_str.lower():
            results.append({"pid": pid, "name": comm, "cmdline": cmdline_str})
    except (PermissionError, FileNotFoundError, ProcessLookupError):
        continue
print(json.dumps(results))
'''


def _in_flatpak() -> bool:
    """Detect if we are running inside a Flatpak sandbox."""
    return Path("/.flatpak-info").exists()


def _host_run_script(script: str, *args: str) -> str:
    """Run a Python script on the host via flatpak-spawn.

    Embeds a marker in the cmdline so the script can filter out
    its own process tree from results.
    """
    tagged_script = f"# {_SCRIPT_MARKER}\n{script}"
    result = subprocess.run(
        ["flatpak-spawn", "--host", "python3", "-c", tagged_script, *args],
        capture_output=True,
        timeout=10,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"Host script failed: {stderr}")
    return result.stdout.decode(errors="replace")


def _host_read(path: str) -> str:
    """Read a file on the host, via flatpak-spawn if sandboxed."""
    if _in_flatpak():
        result = subprocess.run(
            ["flatpak-spawn", "--host", "cat", path],
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0:
            raise FileNotFoundError(path)
        return result.stdout.decode(errors="replace")
    return Path(path).read_text()


@dataclass(frozen=True)
class ProcessInfo:
    """A discovered process."""

    pid: int
    name: str
    cmdline: str


def find_processes(name: str) -> list[ProcessInfo]:
    """Find running processes matching *name* (case-insensitive).

    Uses a single host-side script call when in Flatpak to avoid
    per-PID D-Bus round-trips.
    """
    if _in_flatpak():
        return _find_processes_flatpak(name)
    return _find_processes_native(name)


def _find_processes_flatpak(name: str) -> list[ProcessInfo]:
    """Single flatpak-spawn call that searches all processes on the host."""
    try:
        output = _host_run_script(_FIND_PROCS_SCRIPT, name)
        entries = json.loads(output)
        return [
            ProcessInfo(
                pid=e["pid"], name=e["name"], cmdline=e["cmdline"]
            )
            for e in entries
        ]
    except (RuntimeError, json.JSONDecodeError, subprocess.TimeoutExpired) as e:
        log.error("Process search failed: %s", e)
        return []


def _find_processes_native(name: str) -> list[ProcessInfo]:
    """Direct /proc scan for non-sandboxed environments."""
    results: list[ProcessInfo] = []
    needle = name.lower()
    own_pid = str(os.getpid())

    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        if entry.name == own_pid:
            continue
        try:
            comm = (entry / "comm").read_text().strip()
            if comm in ("python3", "bash", "sh", "flatpak-spawn"):
                continue
            cmdline = (
                (entry / "cmdline")
                .read_bytes()
                .replace(b"\x00", b" ")
                .decode(errors="replace")
                .strip()
            )
            if needle in comm.lower() or needle in cmdline.lower():
                results.append(
                    ProcessInfo(
                        pid=int(entry.name),
                        name=comm,
                        cmdline=cmdline,
                    )
                )
        except (PermissionError, FileNotFoundError, ProcessLookupError):
            continue

    return results


def parse_maps(pid: int) -> dict[str, int]:
    """Parse /proc/<pid>/maps and return {module_name: base_address}.

    Extracts the base address (lowest mapped address) for each unique
    module.  Handles both native ELF paths and Wine/Proton PE paths.
    """
    modules: dict[str, int] = {}

    line_re = re.compile(
        r"^([0-9a-f]+)-[0-9a-f]+\s+"
        r"[r-][w-][x-][ps-]\s+"
        r"[0-9a-f]+\s+"
        r"[0-9a-f]+:[0-9a-f]+\s+"
        r"\d+\s*"
        r"(.*)$"
    )

    try:
        text = _host_read(f"/proc/{pid}/maps")
        for line in text.splitlines():
            m = line_re.match(line)
            if not m:
                continue

            path_str = m.group(2).strip()
            if not path_str or path_str.startswith("["):
                continue

            module_name = Path(path_str).name
            base_addr = int(m.group(1), 16)

            if module_name not in modules or base_addr < modules[module_name]:
                modules[module_name] = base_addr

    except (
        PermissionError,
        FileNotFoundError,
        ProcessLookupError,
        subprocess.TimeoutExpired,
    ) as e:
        log.error("Failed to read maps for PID %d: %s", pid, e)

    return modules
