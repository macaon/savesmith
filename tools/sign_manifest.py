#!/usr/bin/env python3
"""Regenerate and sign the content manifest.

Scans content/definitions/ and content/plugins/, computes SHA256 hashes,
writes content/manifest.json, and signs it with the private key.
"""

import hashlib
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives.serialization import load_pem_private_key

REPO_ROOT = Path(__file__).parent.parent
CONTENT_DIR = REPO_ROOT / "content"
KEYS_DIR = REPO_ROOT / "keys"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def scan_content() -> dict:
    files = {}

    for subdir, file_type in [("definitions", "definition"), ("plugins", "plugin")]:
        content_subdir = CONTENT_DIR / subdir
        if not content_subdir.is_dir():
            continue
        for path in sorted(content_subdir.iterdir()):
            if path.name.startswith(".") or path.name == "__pycache__":
                continue
            if not path.is_file():
                continue
            rel = f"{subdir}/{path.name}"
            files[rel] = {
                "sha256": sha256_file(path),
                "type": file_type,
            }

    return files


def main():
    private_path = KEYS_DIR / "private.pem"
    if not private_path.exists():
        print("No private key found. Run generate_keys.py first.", file=sys.stderr)
        sys.exit(1)

    private_key = load_pem_private_key(private_path.read_bytes(), password=None)

    files = scan_content()
    if not files:
        print("No content files found in content/definitions/ or content/plugins/.")
        sys.exit(1)

    manifest = {
        "version": 1,
        "files": files,
    }

    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode()

    manifest_path = CONTENT_DIR / "manifest.json"
    manifest_path.write_bytes(manifest_bytes)
    print(f"Wrote {manifest_path} ({len(files)} files)")

    signature = private_key.sign(manifest_bytes)
    sig_path = CONTENT_DIR / "manifest.json.sig"
    sig_path.write_bytes(signature)
    print(f"Wrote {sig_path} ({len(signature)} bytes)")

    print("\nManifest contents:")
    for rel, info in files.items():
        print(f"  {rel}: {info['sha256'][:16]}... ({info['type']})")


if __name__ == "__main__":
    main()
