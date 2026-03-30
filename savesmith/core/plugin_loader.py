"""Discover and load plugins from the local data directory."""

from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class PluginInfo:
    """Metadata about a loaded plugin."""

    id: str
    type: str  # "format", "search", or "memory"
    instance: object


class PluginLoader:
    """Manages discovery and loading of plugins."""

    def __init__(self, data_dir: Path):
        self._plugins_dir = data_dir / "plugins"
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
        """Scan plugins dir and load all valid plugins."""
        if not self._plugins_dir.is_dir():
            log.info("No plugins directory at %s", self._plugins_dir)
            return

        for path in sorted(self._plugins_dir.iterdir()):
            if not path.suffix == ".py" or path.name.startswith("_"):
                continue
            self._load_plugin(path)

    def _load_plugin(self, path: Path) -> None:
        """Load a single plugin file."""
        try:
            spec = importlib.util.spec_from_file_location(
                f"savesmith_plugin_{path.stem}", path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Find the plugin class (look for a class with 'id' and 'type')
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
                log.warning(
                    "Unknown plugin type %r in %s",
                    plugin_type,
                    path.name,
                )
                return

            log.info("Loaded %s plugin: %s", plugin_type, plugin_id)

        except Exception:
            log.exception("Failed to load plugin %s", path.name)

    def has_requirements(
        self, requires: tuple[str, ...]
    ) -> tuple[bool, list[str]]:
        """Check if all required plugins are loaded."""
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
