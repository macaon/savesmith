"""Discover, verify, and load plugins from the local data directory."""

from __future__ import annotations

import importlib.util
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from savesmith.core.signing import sha256_bytes

log = logging.getLogger(__name__)


@dataclass
class PluginInfo:
    """Metadata about a loaded plugin."""

    id: str
    type: str  # "format", "search", or "memory"
    instance: object


class PluginLoader:
    """Manages discovery, verification, and loading of plugins."""

    def __init__(self, data_dir: Path):
        self._plugins_dir = data_dir / "plugins"
        self._manifest_path = data_dir / "manifest.json"
        self._format_plugins: dict[str, object] = {}
        self._search_plugins: dict[str, object] = {}
        self._memory_plugins: dict[str, object] = {}

    @property
    def format_plugins(self) -> dict[str, object]:
        return dict(self._format_plugins)

    @property
    def search_plugins(self) -> dict[str, object]:
        return dict(self._search_plugins)

    @property
    def memory_plugins(self) -> dict[str, object]:
        return dict(self._memory_plugins)

    def load_all(self) -> None:
        """Scan plugins dir, verify hashes, and load all valid plugins."""
        if not self._plugins_dir.is_dir():
            log.info("No plugins directory at %s", self._plugins_dir)
            return

        manifest = self._load_manifest()

        for path in sorted(self._plugins_dir.iterdir()):
            if not path.suffix == ".py" or path.name.startswith("_"):
                continue
            self._load_plugin(path, manifest)

    def _load_manifest(self) -> dict:
        """Load the local manifest for hash verification."""
        if not self._manifest_path.exists():
            log.warning("No local manifest — skipping hash verification")
            return {}
        try:
            data = json.loads(self._manifest_path.read_text())
            return data.get("files", {})
        except Exception:
            log.exception("Failed to read manifest")
            return {}

    def _load_plugin(self, path: Path, manifest: dict) -> None:
        """Load a single plugin file after verifying its hash."""
        rel_key = f"plugins/{path.name}"

        # Verify hash against manifest
        if manifest:
            expected = manifest.get(rel_key, {}).get("sha256")
            if expected is None:
                log.warning("Plugin %s not in manifest — skipping", path.name)
                return
            actual = sha256_bytes(path.read_bytes())
            if actual != expected:
                log.error(
                    "Plugin %s hash mismatch — expected %s, got %s — skipping",
                    path.name,
                    expected[:16],
                    actual[:16],
                )
                return

        try:
            spec = importlib.util.spec_from_file_location(
                f"savesmith_plugin_{path.stem}", path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Find the plugin class (look for a class with 'id' and 'type' attributes)
            plugin_class = None
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and hasattr(attr, "id")
                    and hasattr(attr, "type")
                    and attr is not type
                ):
                    plugin_class = attr
                    break

            if plugin_class is None:
                log.warning("No plugin class found in %s", path.name)
                return

            instance = plugin_class()
            plugin_id = instance.id
            plugin_type = instance.type

            if plugin_type == "format":
                self._format_plugins[plugin_id] = instance
            elif plugin_type == "search":
                self._search_plugins[plugin_id] = instance
            elif plugin_type == "memory":
                self._memory_plugins[plugin_id] = instance
            else:
                log.warning("Unknown plugin type %r in %s", plugin_type, path.name)
                return

            log.info("Loaded %s plugin: %s", plugin_type, plugin_id)

        except Exception:
            log.exception("Failed to load plugin %s", path.name)

    def has_requirements(self, requires: tuple[str, ...]) -> tuple[bool, list[str]]:
        """Check if all required plugins are loaded.

        Returns (all_met, list_of_missing_ids).
        """
        all_loaded = {
            **self._format_plugins,
            **self._search_plugins,
            **self._memory_plugins,
        }
        missing = [r for r in requires if r not in all_loaded]
        return len(missing) == 0, missing

    def get_format(self, plugin_id: str) -> object | None:
        return self._format_plugins.get(plugin_id)

    def get_search(self, plugin_id: str) -> object | None:
        return self._search_plugins.get(plugin_id)

    def get_memory(self, plugin_id: str) -> object | None:
        return self._memory_plugins.get(plugin_id)
