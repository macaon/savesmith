"""Read and write process memory via /proc/pid/mem.

When running inside a Flatpak sandbox, delegates to a persistent
helper process on the host via flatpak-spawn.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

# Minimal Python script that runs on the host and serves memory
# read/write requests over stdin/stdout as JSON lines.
_HOST_HELPER = r'''
import json, os, sys
pid = int(sys.argv[1])
fd = os.open(f"/proc/{pid}/mem", os.O_RDWR)
for line in sys.stdin:
    try:
        req = json.loads(line)
        op = req["op"]
        if op == "read":
            os.lseek(fd, req["addr"], os.SEEK_SET)
            data = os.read(fd, req["size"])
            sys.stdout.write(json.dumps({"ok": True, "data": data.hex()}) + "\n")
        elif op == "write":
            os.lseek(fd, req["addr"], os.SEEK_SET)
            os.write(fd, bytes.fromhex(req["data"]))
            sys.stdout.write(json.dumps({"ok": True}) + "\n")
        elif op == "alive":
            alive = os.path.exists(f"/proc/{pid}")
            sys.stdout.write(json.dumps({"ok": True, "alive": alive}) + "\n")
        elif op == "close":
            break
        else:
            sys.stdout.write(json.dumps({"ok": False, "err": "unknown op"}) + "\n")
        sys.stdout.flush()
    except Exception as e:
        sys.stdout.write(json.dumps({"ok": False, "err": str(e)}) + "\n")
        sys.stdout.flush()
os.close(fd)
'''


def _in_flatpak() -> bool:
    return Path("/.flatpak-info").exists()


class ProcessMemory:
    """Read/write access to a process via /proc/<pid>/mem.

    Transparently uses a host-side helper when running in Flatpak.
    """

    def __init__(self, pid: int):
        self._pid = pid
        self._fd: int | None = None
        self._helper: subprocess.Popen | None = None
        self._sandboxed = _in_flatpak()

    def open(self) -> None:
        """Open the memory file or start the host helper."""
        if self._sandboxed:
            self._open_helper()
        else:
            self._open_direct()

    def _open_direct(self) -> None:
        import os

        try:
            self._fd = os.open(
                f"/proc/{self._pid}/mem", os.O_RDWR
            )
        except PermissionError as e:
            raise PermissionError(
                f"Cannot access memory of PID {self._pid}. "
                "Ensure SaveSmith runs as the same user as the game, "
                "and check /proc/sys/kernel/yama/ptrace_scope "
                "(0 = permissive)."
            ) from e
        except FileNotFoundError as e:
            raise ProcessLookupError(
                f"Process {self._pid} no longer exists."
            ) from e

    def _open_helper(self) -> None:
        try:
            self._helper = subprocess.Popen(                [
                    "flatpak-spawn", "--host",
                    "python3", "-c", _HOST_HELPER, str(self._pid),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as e:
            raise RuntimeError(
                "flatpak-spawn not available — "
                "trainer mode requires the Flatpak host portal"
            ) from e

        # Verify the helper started by sending an alive check
        try:
            resp = self._helper_call({"op": "alive"})
            if not resp.get("ok"):
                err = resp.get("err", "unknown error")
                raise PermissionError(
                    f"Cannot access memory of PID {self._pid}: {err}"
                )
        except Exception:
            self.close()
            raise

    def _helper_call(self, request: dict) -> dict:
        """Send a JSON request to the host helper and read the response."""
        if self._helper is None or self._helper.stdin is None:
            raise RuntimeError("Host helper is not running")
        line = json.dumps(request) + "\n"
        self._helper.stdin.write(line.encode())
        self._helper.stdin.flush()
        resp_line = self._helper.stdout.readline()  # type: ignore[union-attr]
        if not resp_line:
            raise OSError("Host helper died unexpectedly")
        return json.loads(resp_line)

    def close(self) -> None:
        """Close the memory file descriptor or stop the helper."""
        if self._helper is not None:
            try:
                if self._helper.stdin:
                    line = json.dumps({"op": "close"}) + "\n"
                    self._helper.stdin.write(line.encode())
                    self._helper.stdin.flush()
                self._helper.terminate()
                self._helper.wait(timeout=2)
            except Exception:
                log.debug("Error during helper cleanup", exc_info=True)
            self._helper = None

        if self._fd is not None:
            import os

            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    def read(self, address: int, size: int) -> bytes:
        """Read *size* bytes from *address* in the target process."""
        if self._sandboxed:
            return self._read_helper(address, size)
        return self._read_direct(address, size)

    def _read_direct(self, address: int, size: int) -> bytes:
        import os

        if self._fd is None:
            raise RuntimeError("ProcessMemory is not open")
        try:
            os.lseek(self._fd, address, os.SEEK_SET)
            return os.read(self._fd, size)
        except OSError as e:
            raise OSError(
                f"Failed to read {size} bytes at 0x{address:X} "
                f"from PID {self._pid}: {e}"
            ) from e

    def _read_helper(self, address: int, size: int) -> bytes:
        resp = self._helper_call({
            "op": "read", "addr": address, "size": size,
        })
        if not resp.get("ok"):
            raise OSError(resp.get("err", "read failed"))
        return bytes.fromhex(resp["data"])

    def write(self, address: int, data: bytes) -> None:
        """Write *data* at *address* in the target process."""
        if self._sandboxed:
            self._write_helper(address, data)
        else:
            self._write_direct(address, data)

    def _write_direct(self, address: int, data: bytes) -> None:
        import os

        if self._fd is None:
            raise RuntimeError("ProcessMemory is not open")
        try:
            os.lseek(self._fd, address, os.SEEK_SET)
            os.write(self._fd, data)
        except OSError as e:
            raise OSError(
                f"Failed to write {len(data)} bytes at 0x{address:X} "
                f"to PID {self._pid}: {e}"
            ) from e

    def _write_helper(self, address: int, data: bytes) -> None:
        resp = self._helper_call({
            "op": "write", "addr": address, "data": data.hex(),
        })
        if not resp.get("ok"):
            raise OSError(resp.get("err", "write failed"))

    def is_alive(self) -> bool:
        """Check if the target process still exists."""
        if self._sandboxed and self._helper is not None:
            try:
                resp = self._helper_call({"op": "alive"})
                return resp.get("alive", False)
            except Exception:
                return False
        return Path(f"/proc/{self._pid}").exists()

    def __enter__(self) -> ProcessMemory:
        self.open()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
