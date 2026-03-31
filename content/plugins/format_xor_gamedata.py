"""XOR format plugin with repeating key 'GameData'."""


class XorGameData:
    id = "format_xor_gamedata"
    type = "format"

    _KEY = b"GameData"

    def decompress(self, data: bytes) -> bytes:
        key = self._KEY
        return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))

    def compress(self, data: bytes) -> bytes:
        # XOR is symmetric
        return self.decompress(data)
