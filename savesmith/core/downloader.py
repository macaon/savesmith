"""Fetch content (definitions + plugins) from the GitHub repository."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

from savesmith.core.signing import verify_manifest, verify_file_hash

log = logging.getLogger(__name__)

# Raw content URL for the macaon/savesmith repo
_BASE_URL = "https://raw.githubusercontent.com/macaon/savesmith/main/content"


class Downloader:
    """Downloads and verifies content from the GitHub repository."""

    def __init__(self, data_dir: Path):
        self._data_dir = data_dir
        self._manifest: dict | None = None

    def fetch_manifest(self) -> dict | None:
        """Fetch and verify the remote manifest. Returns file listing or None."""
        try:
            manifest_bytes = self._fetch(f"{_BASE_URL}/manifest.json")
            sig_bytes = self._fetch(f"{_BASE_URL}/manifest.json.sig")
        except DownloadError as e:
            log.error("Failed to fetch manifest: %s", e)
            return None

        if not verify_manifest(manifest_bytes, sig_bytes):
            return None

        self._manifest = json.loads(manifest_bytes)

        # Save verified manifest locally
        self._data_dir.mkdir(parents=True, exist_ok=True)
        (self._data_dir / "manifest.json").write_bytes(manifest_bytes)

        return self._manifest

    def list_definitions(self) -> list[dict]:
        """Return list of available definitions from the manifest."""
        if self._manifest is None:
            return []
        return [
            {"path": path, **info}
            for path, info in self._manifest.get("files", {}).items()
            if info.get("type") == "definition"
        ]

    def list_plugins(self) -> list[dict]:
        """Return list of available plugins from the manifest."""
        if self._manifest is None:
            return []
        return [
            {"path": path, **info}
            for path, info in self._manifest.get("files", {}).items()
            if info.get("type") == "plugin"
        ]

    def download_file(self, rel_path: str) -> bool:
        """Download a single file, verify its hash, and store locally.

        rel_path is relative to content/, e.g. "definitions/big-ambitions.json"
        """
        if self._manifest is None:
            log.error("No manifest loaded — call fetch_manifest() first")
            return False

        file_info = self._manifest.get("files", {}).get(rel_path)
        if file_info is None:
            log.error("File %s not in manifest", rel_path)
            return False

        try:
            data = self._fetch(f"{_BASE_URL}/{rel_path}")
        except DownloadError as e:
            log.error("Failed to download %s: %s", rel_path, e)
            return False

        if not verify_file_hash(data, file_info["sha256"]):
            return False

        local_path = self._data_dir / rel_path
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(data)
        log.info("Downloaded and verified: %s", rel_path)
        return True

    def download_definition_with_deps(self, def_path: str) -> bool:
        """Download a definition and all plugins it requires."""
        if not self.download_file(def_path):
            return False

        # Parse the definition to find requirements
        local_path = self._data_dir / def_path
        try:
            defn = json.loads(local_path.read_text())
        except Exception:
            log.exception("Failed to parse downloaded definition")
            return False

        requires = defn.get("requires", [])
        all_plugins = {p["path"]: p for p in self.list_plugins()}

        for req_id in requires:
            # Find the plugin file matching this id
            plugin_path = f"plugins/{req_id}.py"
            if plugin_path in all_plugins:
                if not (self._data_dir / plugin_path).exists():
                    if not self.download_file(plugin_path):
                        log.error("Failed to download required plugin: %s", req_id)
                        return False
            else:
                log.warning("Required plugin %s not found in manifest", req_id)

        return True

    @staticmethod
    def _fetch(url: str) -> bytes:
        """Fetch raw bytes from a URL."""
        req = Request(url, headers={"User-Agent": "SaveSmith/0.1"})
        try:
            with urlopen(req, timeout=15) as resp:
                return resp.read()
        except URLError as e:
            raise DownloadError(str(e)) from e


class DownloadError(Exception):
    pass
