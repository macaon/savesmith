"""Pointer chain memory plugin — follow a chain of offsets to read/write."""

import struct


class PointerChainMemory:
    id = "memory_pointer_chain"
    type = "memory"

    _TYPE_FORMATS = {
        "float32": ("<f", 4),
        "float64": ("<d", 8),
        "int8": ("<b", 1),
        "int16": ("<h", 2),
        "int32": ("<i", 4),
        "int64": ("<q", 8),
        "uint8": ("<B", 1),
        "uint16": ("<H", 2),
        "uint32": ("<I", 4),
        "uint64": ("<Q", 8),
        "bool": ("<?", 1),
    }

    def _resolve_chain(self, mem, base: int, chain: list[int]) -> int | None:
        """Follow a pointer chain to resolve the final address.

        Each offset except the last is dereferenced as a 64-bit pointer.
        The last offset is added without dereferencing (field offset).

        Example with chain [0x10, 0x20, 0x30]:
          addr = read_ptr(base + 0x10)
          addr = read_ptr(addr + 0x20)
          final = addr + 0x30

        Returns None if a null pointer is encountered mid-chain.
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
    ) -> object | None:
        """Read a typed value through a pointer chain.

        Returns None if the chain hits a null pointer.
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

        if value_type in ("int32", "int16", "int64", "int8"):
            value = int(value)
        elif value_type in ("uint32", "uint16", "uint64", "uint8"):
            value = int(value)
        elif value_type in ("float32", "float64"):
            value = float(value)
        elif value_type == "bool":
            value = bool(value)

        data = struct.pack(fmt, value)
        mem.write(address, data)
