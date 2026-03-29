"""UTF-16LE field search plugin for .NET binary serialization format.

Searches for field names encoded as UTF-16LE strings in binary data,
then reads/writes values at the offset immediately following the field name.
"""

import struct


class Utf16leFieldSearch:
    id = "search_utf16le"
    type = "search"

    # Map of value types to struct format strings
    _TYPE_FORMATS = {
        "float32": ("<f", 4),
        "int32": ("<i", 4),
        "int16": ("<h", 2),
        "bool": ("<?", 1),
    }

    def find_field(
        self, data: bytes | bytearray, value_type: str, *, field_name: str
    ) -> tuple[int, object]:
        """Find a field by its UTF-16LE name and read its value.

        Returns (offset, value) where offset points to the value bytes.
        """
        needle = field_name.encode("utf-16-le")
        idx = data.find(needle)
        if idx < 0:
            raise FieldNotFoundError(f"Field {field_name!r} not found in save data")

        value_offset = idx + len(needle)
        value = self._read_value(data, value_offset, value_type)
        return value_offset, value

    def write_field(
        self,
        data: bytearray,
        offset: int,
        value_type: str,
        value: object,
    ) -> bytearray:
        """Write a value at the given offset."""
        result = bytearray(data)
        fmt, size = self._TYPE_FORMATS[value_type]
        struct.pack_into(fmt, result, offset, value)
        return result

    def _read_value(
        self, data: bytes | bytearray, offset: int, value_type: str
    ) -> object:
        """Read a value of the given type at offset."""
        if value_type not in self._TYPE_FORMATS:
            raise ValueError(f"Unsupported value type: {value_type}")
        fmt, size = self._TYPE_FORMATS[value_type]
        return struct.unpack_from(fmt, data, offset)[0]


class FieldNotFoundError(Exception):
    pass
