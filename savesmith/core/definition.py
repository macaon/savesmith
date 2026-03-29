"""Load and validate game definition JSON files."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FieldSearch:
    """How to locate a field in the binary save data."""

    method: str  # Plugin id, e.g. "utf16le_field"
    params: dict = field(default_factory=dict)  # Method-specific params


@dataclass(frozen=True)
class FieldDef:
    """A single editable field in a save file."""

    id: str
    name: str
    type: str  # "float32", "int32", "bool", "string"
    widget: str  # "spin", "switch", "entry", "dropdown"
    search: FieldSearch
    category: str = "General"
    min: float | None = None
    max: float | None = None
    step: float | None = None
    options: list[str] | None = None  # For dropdown widget


@dataclass(frozen=True)
class GameDefinition:
    """A complete game definition loaded from JSON."""

    id: str
    name: str
    version: int
    requires: tuple[str, ...]
    save_format_pipeline: tuple[str, ...]  # Ordered list of format plugin ids
    save_glob: str
    fields: tuple[FieldDef, ...]
    meta_glob: str | None = None

    @staticmethod
    def from_json(data: dict) -> GameDefinition:
        fields = []
        for f in data.get("fields", []):
            search_raw = f["search"]
            search = FieldSearch(
                method=search_raw["method"],
                params={k: v for k, v in search_raw.items() if k != "method"},
            )
            fields.append(
                FieldDef(
                    id=f["id"],
                    name=f["name"],
                    type=f["type"],
                    widget=f["widget"],
                    search=search,
                    category=f.get("category", "General"),
                    min=f.get("min"),
                    max=f.get("max"),
                    step=f.get("step"),
                    options=f.get("options"),
                )
            )

        return GameDefinition(
            id=data["id"],
            name=data["name"],
            version=data["version"],
            requires=tuple(data.get("requires", [])),
            save_format_pipeline=tuple(
                data.get("save_format", {}).get("pipeline", [])
            ),
            save_glob=data["save_glob"],
            meta_glob=data.get("meta_glob"),
            fields=tuple(fields),
        )

    @staticmethod
    def from_file(path: Path) -> GameDefinition:
        data = json.loads(path.read_text())
        return GameDefinition.from_json(data)
