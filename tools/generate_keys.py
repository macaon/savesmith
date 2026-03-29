#!/usr/bin/env python3
"""Generate an Ed25519 keypair for signing SaveSmith content.

Run once. Stores the private key in keys/private.pem (git-ignored)
and prints the public key bytes to embed in the app.
"""

import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

KEYS_DIR = Path(__file__).parent.parent / "keys"


def main():
    KEYS_DIR.mkdir(exist_ok=True)

    private_path = KEYS_DIR / "private.pem"
    public_path = KEYS_DIR / "public.pem"

    if private_path.exists():
        print(f"Key already exists at {private_path}", file=sys.stderr)
        print("Delete it first if you want to regenerate.", file=sys.stderr)
        sys.exit(1)

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    # Save private key
    private_pem = private_key.private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
    )
    private_path.write_bytes(private_pem)
    os.chmod(private_path, 0o600)
    print(f"Private key written to {private_path}")

    # Save public key
    public_pem = public_key.public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
    )
    public_path.write_bytes(public_pem)
    print(f"Public key written to {public_path}")

    # Print the raw public key bytes as hex for embedding
    raw_public = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    print(f"\nPublic key (hex, 32 bytes): {raw_public.hex()}")
    print("\nEmbed this in savesmith/core/signing.py as PUBLIC_KEY_HEX.")


if __name__ == "__main__":
    main()
