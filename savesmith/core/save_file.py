"""Open, decompress, recompress, and save game save files."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

log = logging.getLogger(__name__)


class SaveFile:
    """Handles reading and writing a save file through a format plugin pipeline."""

    def __init__(self, path: Path, format_plugins: list):
        self._path = path
        self._format_plugins = format_plugins  # Ordered list of format plugin instances
        self._raw: bytes = b""
        self._data: bytearray = bytearray()  # Decompressed/decrypted inner data

    @property
    def path(self) -> Path:
        return self._path

    @property
    def data(self) -> bytearray:
        """The decompressed inner data (mutable for editing)."""
        return self._data

    @data.setter
    def data(self, value: bytearray) -> None:
        self._data = value

    def load(self) -> None:
        """Read the file and run it through the decompression pipeline."""
        self._raw = self._path.read_bytes()
        current = self._raw

        # Decompress: apply plugins in order
        for plugin in self._format_plugins:
            current = plugin.decompress(current)

        self._data = bytearray(current)
        log.info(
            "Loaded %s: %d bytes raw → %d bytes decompressed",
            self._path.name,
            len(self._raw),
            len(self._data),
        )

    def save(self, backup: bool = True) -> None:
        """Recompress and write the modified data back to disk.

        Creates a .bak backup by default.
        """
        if backup:
            bak_path = self._path.with_suffix(self._path.suffix + ".bak")
            shutil.copy2(self._path, bak_path)
            log.info("Backup saved to %s", bak_path.name)

        current = bytes(self._data)

        # Compress: apply plugins in reverse order
        for plugin in reversed(self._format_plugins):
            current = plugin.compress(current)

        self._path.write_bytes(current)
        self._raw = current
        log.info(
            "Saved %s: %d bytes decompressed → %d bytes compressed",
            self._path.name,
            len(self._data),
            len(current),
        )
