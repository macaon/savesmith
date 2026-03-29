"""Ed25519 signature verification and SHA256 hash checking."""

from __future__ import annotations

import hashlib
import logging

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

log = logging.getLogger(__name__)

# Baked-in public key — set after running tools/generate_keys.py
PUBLIC_KEY_HEX = "1d22c9154c5d0f0c5430237128e92d855d81a3f7f49f07bb14569c3f110a5a15"


def get_public_key() -> Ed25519PublicKey | None:
    """Load the baked-in Ed25519 public key."""
    if not PUBLIC_KEY_HEX:
        log.error("No public key configured — content verification disabled")
        return None
    raw = bytes.fromhex(PUBLIC_KEY_HEX)
    return Ed25519PublicKey.from_public_bytes(raw)


def verify_manifest(manifest_bytes: bytes, signature: bytes) -> bool:
    """Verify that the manifest was signed with our private key."""
    pub = get_public_key()
    if pub is None:
        return False
    try:
        pub.verify(signature, manifest_bytes)
        return True
    except InvalidSignature:
        log.error("Manifest signature verification failed — content may be tampered")
        return False


def sha256_bytes(data: bytes) -> str:
    """Return hex SHA256 digest of data."""
    return hashlib.sha256(data).hexdigest()


def verify_file_hash(data: bytes, expected_sha256: str) -> bool:
    """Verify that file data matches the expected SHA256 hash."""
    actual = sha256_bytes(data)
    if actual != expected_sha256:
        log.error(
            "Hash mismatch: expected %s, got %s",
            expected_sha256[:16],
            actual[:16],
        )
        return False
    return True
