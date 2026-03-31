"""JSON path search plugin — find and modify values in JSON save data."""

import json


class JsonFieldSearch:
    id = "search_json"
    type = "search"

    def __init__(self):
        self._paths: dict[int, str] = {}
        self._path_counter = 0

    def find_field(
        self, data: bytes | bytearray, value_type: str, *, json_path: str
    ) -> tuple[int, object]:
        """Find a field by dotted JSON path.

        Returns (pseudo_offset, value). The pseudo_offset maps back
        to the path during write_field.
        """
        obj = json.loads(data)
        value = self._get_path(obj, json_path)

        self._path_counter += 1
        pseudo_offset = self._path_counter
        self._paths[pseudo_offset] = json_path

        return pseudo_offset, value

    def write_field(
        self,
        data: bytearray,
        offset: int,
        value_type: str,
        value: object,
    ) -> bytearray:
        """Set a value at a previously found JSON path."""
        obj = json.loads(data)
        path = self._paths.get(offset, "")
        if not path:
            return data

        self._set_path(obj, path, value, value_type)
        return bytearray(
            json.dumps(obj, ensure_ascii=False).encode()
        )

    @staticmethod
    def _get_path(obj: dict, path: str) -> object:
        """Navigate a dotted path like 'PlayerInfo.m_Gold'."""
        for key in path.split("."):
            obj = obj[key]
        return obj

    @staticmethod
    def _set_path(
        obj: dict, path: str, value: object, value_type: str
    ) -> None:
        """Set a value at a dotted path."""
        keys = path.split(".")
        for key in keys[:-1]:
            obj = obj[key]
        if value_type in ("int32", "int16"):
            value = int(value)
        elif value_type == "float32":
            value = float(value)
        elif value_type == "bool":
            value = bool(value)
        obj[keys[-1]] = value
