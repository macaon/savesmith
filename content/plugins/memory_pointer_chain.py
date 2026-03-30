"""Pointer chain memory plugin — follow a chain of offsets to read/write."""

import struct


class PointerChainMemory:
    id = "memory_pointer_chain"
    type = "memory"

    _TYPE_FORMATS = {
        "float32": ("<f", 4),
        "int32": ("<i", 4),
        "int16": ("<h", 2),
        "bool": ("<?", 1),
    }

    def _resolve_chain(self, mem, base: int, chain: list[int]) -> int | None:
        """Follow a pointer chain to resolve the final address.

        Given base and chain [0x10, 0x610]:
          addr = read_ptr(base + 0x10)
          final = addr + 0x610
        The last offset is NOT dereferenced — it's the field offset.
        Returns None if a null pointer is encountered.
        """
        addr = base
        for offset in chain[:-1]:
            ptr_data = mem.read(addr + offset, 8)
            addr = struct.unpack("<Q", ptr_data)[0]
            if addr == 0:
                return None
        return addr + chain[-1]

    def _resolve_with_fallback(
        self, mem, base: int, offset: int, chain=None, fallback_chain=None
    ) -> int | None:
        """Resolve address, trying chain first then fallback_chain."""
        if chain:
            address = self._resolve_chain(mem, base, chain)
            if address is not None:
                return address
        if fallback_chain:
            return self._resolve_chain(mem, base, fallback_chain)
        if chain:
            return None
        return base + offset

    def read_value(
        self, mem, base: int, offset: int, value_type: str,
        *, chain=None, fallback_chain=None
    ) -> object:
        """Read a typed value through a pointer chain.

        If chain is provided, offset is ignored and the chain is followed
        from base.  Otherwise falls back to simple base+offset.
        """
        if value_type not in self._TYPE_FORMATS:
            raise ValueError(f"Unsupported value type: {value_type}")
        fmt, size = self._TYPE_FORMATS[value_type]

        address = self._resolve_with_fallback(
            mem, base, offset, chain, fallback_chain
        )
        if address is None:
            return None

        data = mem.read(address, size)
        return struct.unpack(fmt, data)[0]

    def write_value(
        self, mem, base: int, offset: int, value_type: str, value: object,
        *, chain=None, fallback_chain=None
    ) -> None:
        """Write a typed value through a pointer chain."""
        if value_type not in self._TYPE_FORMATS:
            raise ValueError(f"Unsupported value type: {value_type}")
        fmt, _size = self._TYPE_FORMATS[value_type]

        address = self._resolve_with_fallback(
            mem, base, offset, chain, fallback_chain
        )
        if address is None:
            return

        if value_type in ("int32", "int16"):
            value = int(value)
        elif value_type == "bool":
            value = bool(value)

        data = struct.pack(fmt, value)
        mem.write(address, data)
