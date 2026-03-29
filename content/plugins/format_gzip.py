"""Gzip format plugin — compress and decompress gzip data."""

import gzip


class GzipFormat:
    id = "format_gzip"
    type = "format"

    def decompress(self, data: bytes) -> bytes:
        return gzip.decompress(data)

    def compress(self, data: bytes) -> bytes:
        return gzip.compress(data)
