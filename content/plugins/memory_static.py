"""Static memory address plugin — read/write at module base + fixed offset."""

import struct


class StaticMemory:
    id = "memory_static"
    type = "memory"

    _TYPE_FORMATS = {
        "float32": ("<f", 4),
        "int32": ("<i", 4),
        "int16": ("<h", 2),
        "bool": ("<?", 1),
    }

    def read_value(self, mem, base: int, offset: int, value_type: str) -> object:
        """Read a typed value at base + offset from process memory."""
        if value_type not in self._TYPE_FORMATS:
            raise ValueError(f"Unsupported value type: {value_type}")
        fmt, size = self._TYPE_FORMATS[value_type]
        address = base + offset
        data = mem.read(address, size)
        return struct.unpack(fmt, data)[0]

    def write_value(
        self, mem, base: int, offset: int, value_type: str, value: object
    ) -> None:
        """Write a typed value at base + offset to process memory."""
        if value_type not in self._TYPE_FORMATS:
            raise ValueError(f"Unsupported value type: {value_type}")
        fmt, _size = self._TYPE_FORMATS[value_type]
        address = base + offset
        if value_type in ("int32", "int16"):
            value = int(value)
        elif value_type == "bool":
            value = bool(value)
        data = struct.pack(fmt, value)
        mem.write(address, data)
