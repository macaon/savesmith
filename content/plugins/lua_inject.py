"""Lua injection plugin — execute Lua code in a target process.

Finds lua_State* and Lua C API function addresses at init time,
then executes arbitrary Lua code strings by writing shellcode into
the target's memory and redirecting execution via GDB.

Works with LuaJIT (lua51.dll) in Wine/Proton processes.
"""

import logging
import struct
import subprocess

log = logging.getLogger(__name__)


class LuaInject:
    id = "lua_inject"
    type = "memory"

    def __init__(self):
        self._pid = None
        self._lua_state = None
        self._luaL_loadstring = None
        self._lua_pcall = None
        self._code_addr = None
        self._str_addr = None
        self._in_flatpak = False

    def attach(self, pid: int, mem, module_bases: dict) -> bool:
        """Find lua_State and Lua API addresses.

        Returns True if Lua injection is available.
        """
        self._pid = pid
        self._in_flatpak = _in_flatpak()
        self._mem = mem

        # Find Lua function addresses via GDB
        addrs = self._gdb_find_lua_addrs()
        if not addrs:
            log.error("Could not find Lua API functions")
            return False

        self._luaL_loadstring = addrs["luaL_loadstring"]
        self._lua_pcall = addrs["lua_pcall"]
        self._lua_settop = addrs.get("lua_settop")

        # Find lua_State* by breaking on a Lua function
        self._lua_state = self._gdb_find_lua_state()
        if not self._lua_state:
            log.error("Could not find lua_State*")
            return False

        # Find rwx memory for shellcode
        self._code_addr = self._find_rwx_region()
        if not self._code_addr:
            log.error("No rwx memory region found")
            return False

        # String goes 256 bytes before code
        self._str_addr = self._code_addr - 0x100

        log.info(
            "Lua inject ready: L=0x%X loadstring=0x%X pcall=0x%X",
            self._lua_state,
            self._luaL_loadstring,
            self._lua_pcall,
        )
        return True

    def execute(self, lua_code: str) -> bool:
        """Execute a Lua code string in the target process."""
        if not self._lua_state:
            return False

        # Write the Lua code string to target memory
        code_bytes = lua_code.encode("utf-8") + b"\x00"
        self._mem.write(self._str_addr, code_bytes)

        # Build and write shellcode
        shellcode = self._build_shellcode()
        self._mem.write(self._code_addr, shellcode)

        # Execute via GDB
        return self._gdb_execute_shellcode()

    # -- Plugin interface stubs (not used for lua_inject) --

    def read_value(self, mem, base, offset, value_type, **kwargs):
        return None

    def write_value(
        self, mem, base, offset, value_type, value, **kwargs
    ):
        pass

    # -- Internal methods --

    def _gdb_cmd(self, *gdb_args: str) -> str:
        """Run GDB in batch mode against the target."""
        cmd = [
            "gdb", "-batch", "-q",
            "-ex", "set debuginfod enabled off",
            "-ex", "set auto-solib-add off",
        ]
        for arg in gdb_args:
            cmd.extend(["-ex", arg])

        if self._in_flatpak:
            cmd = ["flatpak-spawn", "--host"] + cmd

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.stdout

    def _gdb_find_lua_addrs(self) -> dict | None:
        """Find luaL_loadstring, lua_pcall, lua_settop addresses."""
        output = self._gdb_cmd(
            "set auto-solib-add on",
            f"attach {self._pid}",
            "p/x (void*)luaL_loadstring",
            "p/x (void*)lua_pcall",
            "p/x (void*)lua_settop",
            "detach",
        )
        addrs = {}
        names = ["luaL_loadstring", "lua_pcall", "lua_settop"]
        idx = 0
        for line in output.splitlines():
            if line.strip().startswith("$") and "=" in line:
                val = _parse_gdb_hex(line)
                if val and idx < len(names):
                    addrs[names[idx]] = val
                idx += 1

        if len(addrs) >= 2:
            return addrs
        return None

    def _gdb_find_lua_state(self) -> int | None:
        """Find lua_State* by breaking on a Lua function."""
        bp = (
            f"break *0x{self._lua_settop:x}"
            if self._lua_settop
            else "break lua_settop"
        )
        output = self._gdb_cmd(
            "set auto-solib-add on",
            f"attach {self._pid}",
            "handle all nostop noprint pass",
            "handle SIGTRAP stop nopass",
            bp,
            "continue",
            'printf "__L=0x%lx\\n", $rcx',
            "delete breakpoints",
            "detach",
        )
        for line in output.splitlines():
            if line.startswith("__L="):
                try:
                    return int(line.split("=")[1], 16)
                except ValueError:
                    pass
        return None

    def _find_rwx_region(self) -> int | None:
        """Find an rwx region in the 32-bit address space."""
        maps = _read_maps(self._pid, self._in_flatpak)
        for line in maps.splitlines():
            parts = line.split()
            if len(parts) < 2 or "rwx" not in parts[1]:
                continue
            start, end = [int(x, 16) for x in parts[0].split("-")]
            size = end - start
            if size >= 0x200 and end < 0x100000000:
                # Use near the end to avoid conflicts
                return end - 0x200
        # Also check 64-bit rwx regions
        for line in maps.splitlines():
            parts = line.split()
            if len(parts) < 2 or "rwx" not in parts[1]:
                continue
            start, end = [int(x, 16) for x in parts[0].split("-")]
            size = end - start
            if size >= 0x200:
                return end - 0x200
        return None

    def _build_shellcode(self) -> bytes:
        """Build x86-64 shellcode for luaL_loadstring + lua_pcall."""
        sc = bytearray()
        # sub rsp, 0x28 (shadow space + alignment)
        sc += b"\x48\x83\xec\x28"
        # mov rcx, lua_state (L)
        sc += b"\x48\xb9" + struct.pack("<Q", self._lua_state)
        # mov rdx, str_addr
        sc += b"\x48\xba" + struct.pack("<Q", self._str_addr)
        # mov rax, luaL_loadstring
        sc += b"\x48\xb8" + struct.pack(
            "<Q", self._luaL_loadstring
        )
        # call rax
        sc += b"\xff\xd0"
        # mov rcx, lua_state (L)
        sc += b"\x48\xb9" + struct.pack("<Q", self._lua_state)
        # xor edx, edx (nargs=0)
        sc += b"\x31\xd2"
        # xor r8d, r8d (nresults=0)
        sc += b"\x45\x31\xc0"
        # xor r9d, r9d (errfunc=0)
        sc += b"\x45\x31\xc9"
        # mov rax, lua_pcall
        sc += b"\x48\xb8" + struct.pack("<Q", self._lua_pcall)
        # call rax
        sc += b"\xff\xd0"
        # add rsp, 0x28
        sc += b"\x48\x83\xc4\x28"
        # int3 (trap for GDB to catch)
        sc += b"\xcc"
        return bytes(sc)

    def _gdb_execute_shellcode(self) -> bool:
        """Redirect execution to shellcode via GDB."""
        saved_regs = ["rip", "rsp", "rax", "rcx", "rdx",
                      "r8", "r9", "rbx"]

        bp = (
            f"break *0x{self._lua_settop:x}"
            if self._lua_settop
            else "break lua_settop"
        )
        args = [
            f"attach {self._pid}",
            "handle all nostop noprint pass",
            "handle SIGTRAP stop nopass",
            "set unwind-on-signal on",
            bp,
            "continue",
            "delete breakpoints",
        ]
        for reg in saved_regs:
            args.append(f"set $saved_{reg} = ${reg}")
        args.append(f"set $rip = {self._code_addr}")
        args.append("continue")
        for reg in saved_regs:
            args.append(f"set ${reg} = $saved_{reg}")
        args.append("detach")

        try:
            output = self._gdb_cmd(*args)
            success = "SIGTRAP" in output
            if success:
                log.info("Lua code executed successfully")
            else:
                log.error(
                    "Lua execution failed: %s", output[-200:]
                )
            return success
        except subprocess.TimeoutExpired:
            log.error("GDB timed out during Lua execution")
            return False


def _in_flatpak() -> bool:
    from pathlib import Path
    return Path("/.flatpak-info").exists()


def _read_maps(pid: int, in_flatpak: bool) -> str:
    if in_flatpak:
        result = subprocess.run(
            ["flatpak-spawn", "--host", "cat", f"/proc/{pid}/maps"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout
    from pathlib import Path
    return Path(f"/proc/{pid}/maps").read_text()


def _parse_gdb_hex(line: str) -> int | None:
    """Extract a hex value from a GDB output line like '$1 = 0x...'"""
    try:
        for part in line.split():
            if part.startswith("0x"):
                return int(part.rstrip(">"), 16)
    except ValueError:
        pass
    return None
