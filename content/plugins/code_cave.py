"""Code cave plugin — install guarded patches via rwx trampolines.

Writes guard shellcode + stolen bytes to an rwx region, then replaces
the original code with a jmp to the cave. On disable, restores the
stolen bytes.
"""

import logging
import struct

log = logging.getLogger(__name__)


class CodeCave:
    id = "code_cave"
    type = "memory"

    def __init__(self):
        self._caves: dict[int, int] = {}  # patch_addr -> cave_addr

    def install(self, mem, pid: int, addr: int, original: bytes,
                cave_code: bytes) -> bool:
        """Install a code cave at the given address.

        Args:
            mem: ProcessMemory instance
            pid: target process ID
            addr: address of the code to patch
            original: stolen bytes (original code at addr)
            cave_code: guard shellcode (runs before stolen bytes)

        Returns True on success.
        """
        cave_base = self._find_rwx(pid, near=addr)
        if cave_base == 0:
            log.error("No rwx region within jmp32 range of 0x%X", addr)
            return False

        return_addr = addr + len(original)

        # Build cave: guard + stolen bytes + jmp back
        cave = bytearray(cave_code)
        cave += original
        jmp_back = return_addr - (cave_base + len(cave) + 5)
        try:
            cave += b"\xE9" + struct.pack("<i", jmp_back)
        except struct.error:
            log.error(
                "Jump back offset too large: 0x%X -> 0x%X",
                cave_base + len(cave), return_addr,
            )
            return False

        # Write cave
        mem.write(cave_base, bytes(cave))

        # Build trampoline: jmp to cave + NOP padding
        jmp_to_cave = cave_base - (addr + 5)
        try:
            trampoline = b"\xE9" + struct.pack("<i", jmp_to_cave)
        except struct.error:
            log.error(
                "Jump to cave offset too large: 0x%X -> 0x%X",
                addr, cave_base,
            )
            return False
        trampoline += b"\x90" * (len(original) - 5)

        mem.write(addr, trampoline)
        self._caves[addr] = cave_base

        log.info(
            "Code cave at 0x%X -> 0x%X (%d bytes)",
            addr, cave_base, len(cave),
        )
        return True

    def uninstall(self, mem, addr: int, original: bytes) -> None:
        """Restore original bytes at the patched address."""
        mem.write(addr, original)
        self._caves.pop(addr, None)

    def _find_rwx(self, pid: int, near: int) -> int:
        """Find an rwx region within jmp32 range of near."""
        try:
            maps_text = self._read_maps(pid)
        except Exception:
            return 0

        best = 0
        best_dist = 0x7FFFFFFFFFFFFFFF
        for line in maps_text.splitlines():
            parts = line.split()
            if len(parts) < 2 or "rwx" not in parts[1]:
                continue
            start, end = [int(x, 16) for x in parts[0].split("-")]
            if (end - start) < 0x1000:
                continue
            candidate = end - 0x800
            dist = abs(candidate - near)
            if dist < best_dist and dist < 0x7FFFFFFF:
                best = candidate
                best_dist = dist

        return best

    @staticmethod
    def _read_maps(pid: int) -> str:
        from pathlib import Path

        if Path("/.flatpak-info").exists():
            import subprocess
            result = subprocess.run(
                ["flatpak-spawn", "--host", "cat",
                 f"/proc/{pid}/maps"],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout
        return Path(f"/proc/{pid}/maps").read_text()

    # Plugin interface stubs (not used directly)
    def read_value(self, mem, base, offset, value_type, **kw):
        return None

    def write_value(self, mem, base, offset, value_type, value, **kw):
        pass
