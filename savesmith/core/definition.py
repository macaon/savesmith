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


# ---------------------------------------------------------------------------
# Trainer definitions (live process memory editing)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldAddress:
    """How to locate a field in process memory."""

    method: str  # Memory plugin id, e.g. "memory_static"
    module: str  # Module name to resolve base address, e.g. "Game.exe"
    offset: int  # Byte offset from module base
    chain: tuple[int, ...] = ()  # Pointer chain offsets for indirection
    fallback_chain: tuple[int, ...] = ()  # Used if chain hits a null ptr


@dataclass(frozen=True)
class CodePatch:
    """A single byte patch to apply to the game's code."""

    offset: int  # Offset from module base
    original: bytes  # Expected original bytes (for verification + restore)
    patch: bytes  # Replacement bytes


@dataclass(frozen=True)
class PatchWrite:
    """A value to write when a patch is enabled."""

    offset: int  # Offset from resolved address
    type: str  # "int32", "float32", etc.
    value: int | float


@dataclass(frozen=True)
class PatchAction:
    """Writes to perform when a patch is toggled on."""

    chain: tuple[int, ...]  # Pointer chain to resolve base
    writes: tuple[PatchWrite, ...]


@dataclass(frozen=True)
class TrainerFieldDef:
    """A single editable field in process memory."""

    id: str
    name: str
    type: str  # "float32", "int32", "int16", "bool", "patch"
    widget: str  # "spin", "switch", "entry"
    address: FieldAddress | None = None
    category: str = "General"
    freezable: bool = False
    min: float | None = None
    max: float | None = None
    step: float | None = None
    options: list[str] | None = None
    patches: tuple[CodePatch, ...] = ()  # For type="patch" fields
    on_enable: PatchAction | None = None  # Writes to run when patch enabled
    on_enable_alt: PatchAction | None = None  # Additional writes (null-safe)
    freeze_on_enable: bool = False  # Repeat on_enable writes every poll tick
    on_enable_lua: str = ""  # Lua code to execute when enabled
    on_disable_lua: str = ""  # Lua code to execute when disabled


@dataclass(frozen=True)
class TrainerDefinition:
    """A trainer definition for live process memory editing."""

    id: str
    name: str
    version: int
    requires: tuple[str, ...]
    process_name: str
    fields: tuple[TrainerFieldDef, ...]
    poll_interval_ms: int = 500
    game_version: str = ""

    @staticmethod
    def from_json(data: dict) -> TrainerDefinition:
        fields = []
        for f in data.get("fields", []):
            field_type = f["type"]

            # Parse address (not present for patch fields)
            address = None
            if "address" in f:
                addr_raw = f["address"]
                raw_chain = addr_raw.get("chain", [])
                chain = tuple(
                    int(c, 16) if isinstance(c, str) else c
                    for c in raw_chain
                )
                raw_fb = addr_raw.get("fallback_chain", [])
                fallback_chain = tuple(
                    int(c, 16) if isinstance(c, str) else c
                    for c in raw_fb
                )
                address = FieldAddress(
                    method=addr_raw["method"],
                    module=addr_raw["module"],
                    offset=int(addr_raw["offset"], 16)
                    if isinstance(addr_raw["offset"], str)
                    else addr_raw["offset"],
                    chain=chain,
                    fallback_chain=fallback_chain,
                )

            # Parse code patches
            patches = tuple(
                CodePatch(
                    offset=int(p["offset"], 16)
                    if isinstance(p["offset"], str)
                    else p["offset"],
                    original=bytes.fromhex(p["original"]),
                    patch=bytes.fromhex(p["patch"]),
                )
                for p in f.get("patches", [])
            )

            # Parse on_enable action
            on_enable = None
            oe_raw = f.get("on_enable")
            if oe_raw:
                oe_chain = tuple(
                    int(c, 16) if isinstance(c, str) else c
                    for c in oe_raw.get("chain", [])
                )
                oe_writes = tuple(
                    PatchWrite(
                        offset=int(w["offset"], 16)
                        if isinstance(w["offset"], str)
                        else w["offset"],
                        type=w["type"],
                        value=w["value"],
                    )
                    for w in oe_raw.get("writes", [])
                )
                on_enable = PatchAction(
                    chain=oe_chain, writes=oe_writes
                )

            # Parse on_enable_alt action
            on_enable_alt = None
            oea_raw = f.get("on_enable_alt")
            if oea_raw:
                oea_chain = tuple(
                    int(c, 16) if isinstance(c, str) else c
                    for c in oea_raw.get("chain", [])
                )
                oea_writes = tuple(
                    PatchWrite(
                        offset=int(w["offset"], 16)
                        if isinstance(w["offset"], str)
                        else w["offset"],
                        type=w["type"],
                        value=w["value"],
                    )
                    for w in oea_raw.get("writes", [])
                )
                on_enable_alt = PatchAction(
                    chain=oea_chain, writes=oea_writes
                )

            fields.append(
                TrainerFieldDef(
                    id=f["id"],
                    name=f["name"],
                    type=field_type,
                    widget=f["widget"],
                    address=address,
                    category=f.get("category", "General"),
                    freezable=f.get("freezable", False),
                    min=f.get("min"),
                    max=f.get("max"),
                    step=f.get("step"),
                    options=f.get("options"),
                    patches=patches,
                    on_enable=on_enable,
                    on_enable_alt=on_enable_alt,
                    freeze_on_enable=f.get("freeze_on_enable", False),
                    on_enable_lua=f.get("on_enable_lua", ""),
                    on_disable_lua=f.get("on_disable_lua", ""),
                )
            )

        return TrainerDefinition(
            id=data["id"],
            name=data["name"],
            version=data["version"],
            requires=tuple(data.get("requires", [])),
            process_name=data["process_name"],
            poll_interval_ms=data.get("poll_interval_ms", 500),
            game_version=data.get("game_version", ""),
            fields=tuple(fields),
        )

    @staticmethod
    def from_file(path: Path) -> TrainerDefinition:
        data = json.loads(path.read_text())
        return TrainerDefinition.from_json(data)


def load_definition(path: Path) -> GameDefinition | TrainerDefinition:
    """Load a definition file and return the correct type based on mode."""
    data = json.loads(path.read_text())
    mode = data.get("mode", "save")
    if mode == "trainer":
        return TrainerDefinition.from_json(data)
    return GameDefinition.from_json(data)
