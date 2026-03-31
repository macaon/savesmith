"""Trainer editor — live read/write of process memory fields."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from savesmith.core.definition import TrainerDefinition, TrainerFieldDef
from savesmith.core.memory import ProcessMemory
from savesmith.core.process import parse_maps

log = logging.getLogger(__name__)


@dataclass
class TrainerFieldValue:
    """A field's live state in the trainer."""

    field: TrainerFieldDef
    module_base: int
    current_value: object = None
    frozen: bool = False
    frozen_value: object = None

    @property
    def display_value(self) -> object:
        return self.frozen_value if self.frozen else self.current_value


def _plugin_kwargs(field_def: TrainerFieldDef) -> dict:
    """Build extra keyword arguments for plugin read/write calls."""
    if field_def.address is None:
        return {}
    kwargs = {}
    if field_def.address.chain:
        kwargs["chain"] = list(field_def.address.chain)
    if field_def.address.fallback_chain:
        kwargs["fallback_chain"] = list(field_def.address.fallback_chain)
    return kwargs


class TrainerEditor:
    """Reads and writes field values in a running process."""

    def __init__(
        self,
        pid: int,
        definition: TrainerDefinition,
        memory_plugins: dict[str, object],
    ):
        self._pid = pid
        self._definition = definition
        self._memory_plugins = memory_plugins
        self._mem = ProcessMemory(pid)
        self._field_values: list[TrainerFieldValue] = []
        self._module_bases: dict[str, int] = {}
        self._lua_plugin: object | None = None
        self._attached = False

    @property
    def field_values(self) -> list[TrainerFieldValue]:
        return list(self._field_values)

    @property
    def attached(self) -> bool:
        return self._attached

    def attach(self) -> None:
        """Open process memory and resolve module bases."""
        self._mem.open()
        self._module_bases = parse_maps(self._pid)
        self._attached = True
        log.info(
            "Attached to PID %d, found %d modules",
            self._pid,
            len(self._module_bases),
        )

        # Initialize Lua injection if any field needs it
        needs_lua = any(
            f.on_enable_lua or f.on_disable_lua
            for f in self._definition.fields
        )
        if needs_lua:
            lua = self._memory_plugins.get("lua_inject")
            if lua and hasattr(lua, "attach"):
                if lua.attach(self._pid, self._mem, self._module_bases):
                    self._lua_plugin = lua
                    log.info("Lua injection initialized")
                else:
                    log.warning("Lua injection not available")

    def _resolve_base(self, module: str) -> int:
        """Resolve a module name to its base address."""
        base = self._module_bases.get(module, 0)
        if base == 0:
            for mod_name, mod_base in self._module_bases.items():
                if mod_name.lower() == module.lower():
                    return mod_base
        return base

    def read_fields(self) -> list[TrainerFieldValue]:
        """Resolve addresses and read all field values."""
        self._field_values = []

        for field_def in self._definition.fields:
            if field_def.type == "patch":
                self._read_patch_field(field_def)
                continue

            if field_def.address is None:
                continue

            plugin = self._memory_plugins.get(field_def.address.method)
            if plugin is None:
                log.warning(
                    "No memory plugin %r for field %s — skipping",
                    field_def.address.method,
                    field_def.id,
                )
                continue

            base = self._resolve_base(field_def.address.module)
            if base == 0:
                log.warning(
                    "Module %r not found for field %s — skipping",
                    field_def.address.module,
                    field_def.id,
                )
                continue

            try:
                value = plugin.read_value(
                    self._mem,
                    base,
                    field_def.address.offset,
                    field_def.type,
                    **_plugin_kwargs(field_def),
                )
                self._field_values.append(
                    TrainerFieldValue(
                        field=field_def,
                        module_base=base,
                        current_value=value,
                    )
                )
                if value is None:
                    log.info(
                        "Field %s unavailable (null pointer)",
                        field_def.id,
                    )
                else:
                    log.debug("Field %s = %r", field_def.id, value)
            except OSError:
                log.exception(
                    "Failed to read field %s", field_def.id
                )

        return self._field_values

    def _read_patch_field(self, field_def: TrainerFieldDef) -> None:
        """Add a patch field, checking if patches are currently active."""
        has_patches = bool(field_def.patches)
        has_freeze = field_def.freeze_on_enable
        has_lua = bool(field_def.on_enable_lua)

        if not has_patches and not has_freeze and not has_lua:
            return

        base = 0
        if field_def.address:
            module = field_def.address.module
            base = self._resolve_base(module)
        elif has_patches:
            base = self._resolve_base(
                self._definition.process_name
            )

        if has_patches and base == 0:
            log.warning(
                "Module not found for patch field %s",
                field_def.id,
            )
            return

        # Check if patches are currently applied
        if field_def.patches:
            active = True
            try:
                for cp in field_def.patches:
                    current = self._mem.read(
                        base + cp.offset, len(cp.patch)
                    )
                    if current != cp.patch:
                        active = False
                        break
            except OSError:
                active = False
        else:
            # Freeze-only fields start inactive
            active = False

        self._field_values.append(
            TrainerFieldValue(
                field=field_def,
                module_base=base,
                current_value=active,
            )
        )
        log.debug("Patch field %s: active=%s", field_def.id, active)

    def _run_patch_action(
        self, fv: TrainerFieldValue, action: object
    ) -> None:
        """Execute writes for a patch on_enable action."""
        import struct

        type_fmts = {
            "int32": ("<i", 4),
            "float32": ("<f", 4),
            "int16": ("<h", 2),
            "bool": ("<?", 1),
        }

        # Resolve the chain to get the base address for writes
        if action.chain:
            addr = fv.module_base
            for off in action.chain[:-1]:
                ptr_data = self._mem.read(addr + off, 8)
                addr = struct.unpack("<Q", ptr_data)[0]
                if addr == 0:
                    log.debug("Null pointer in on_enable chain")
                    return
            base = addr + action.chain[-1]
        else:
            base = fv.module_base

        for w in action.writes:
            fmt, size = type_fmts[w.type]
            val = int(w.value) if w.type in ("int32", "int16") else w.value
            data = struct.pack(fmt, val)
            self._mem.write(base + w.offset, data)
            log.debug(
                "on_enable write: 0x%X = %r", base + w.offset, w.value
            )

    def _apply_cave_patch(self, addr: int, cp) -> None:
        """Install a code cave via the code_cave plugin."""
        cave_plugin = self._memory_plugins.get("code_cave")
        if cave_plugin is None:
            log.error("code_cave plugin not loaded")
            return
        cave_plugin.install(
            self._mem, self._pid, addr, cp.original, cp.cave
        )

    def toggle_patch(self, field_id: str, enable: bool) -> None:
        """Apply or restore code patches for a patch field."""
        for fv in self._field_values:
            if fv.field.id != field_id:
                continue
            if fv.field.type != "patch":
                return

            try:
                for cp in fv.field.patches:
                    addr = fv.module_base + cp.offset
                    if enable:
                        # Verify original bytes before patching
                        current = self._mem.read(addr, len(cp.original))
                        if current != cp.original:
                            # Check if already patched
                            if cp.cave:
                                # Cave patch: check for jmp
                                if current[0] != 0xE9:
                                    log.error(
                                        "Patch %s: unexpected bytes "
                                        "at 0x%X: %s",
                                        field_id, addr,
                                        current.hex(),
                                    )
                                    return
                                else:
                                    continue  # already applied
                            elif current != cp.patch:
                                log.error(
                                    "Patch %s: unexpected bytes "
                                    "at 0x%X: %s (expected %s)",
                                    field_id, addr,
                                    current.hex(),
                                    cp.original.hex(),
                                )
                                return
                            else:
                                continue  # already applied

                        if cp.cave:
                            self._apply_cave_patch(addr, cp)
                        else:
                            self._mem.write(addr, cp.patch)
                    else:
                        if cp.cave:
                            # Restore stolen bytes
                            self._mem.write(addr, cp.original)
                        else:
                            self._mem.write(addr, cp.original)

                # Run on_enable writes
                if enable and fv.field.on_enable:
                    self._run_patch_action(fv, fv.field.on_enable)
                if enable and fv.field.on_enable_alt:
                    try:
                        self._run_patch_action(
                            fv, fv.field.on_enable_alt
                        )
                    except OSError:
                        log.debug(
                            "on_enable_alt skipped for %s (null ptr)",
                            field_id,
                        )

                # Run Lua code
                if self._lua_plugin:
                    lua_code = (
                        fv.field.on_enable_lua
                        if enable
                        else fv.field.on_disable_lua
                    )
                    if lua_code:
                        self._lua_plugin.execute(lua_code)

                fv.current_value = enable
                log.info(
                    "Patch %s %s",
                    field_id,
                    "enabled" if enable else "disabled",
                )
            except OSError:
                log.exception("Failed to toggle patch %s", field_id)
            return

    def poll(self) -> list[TrainerFieldValue]:
        """Re-read all fields; re-write frozen values."""
        if not self._mem.is_alive():
            self._attached = False
            return self._field_values

        for fv in self._field_values:
            # Freeze-on-enable patch fields: repeat writes every tick
            if (
                fv.field.type == "patch"
                and fv.field.freeze_on_enable
                and fv.current_value
            ):
                try:
                    if fv.field.on_enable:
                        self._run_patch_action(fv, fv.field.on_enable)
                    if fv.field.on_enable_alt:
                        try:
                            self._run_patch_action(
                                fv, fv.field.on_enable_alt
                            )
                        except OSError:
                            pass
                except OSError:
                    log.warning(
                        "Lost access to field %s", fv.field.id
                    )
                    self._attached = False
                    return self._field_values
                continue

            # Regular patch fields don't need polling
            if fv.field.type == "patch":
                continue

            if fv.field.address is None:
                continue

            plugin = self._memory_plugins.get(fv.field.address.method)
            if plugin is None:
                continue

            kwargs = _plugin_kwargs(fv.field)

            try:
                if fv.frozen and fv.frozen_value is not None:
                    plugin.write_value(
                        self._mem,
                        fv.module_base,
                        fv.field.address.offset,
                        fv.field.type,
                        fv.frozen_value,
                        **kwargs,
                    )
                    fv.current_value = fv.frozen_value
                else:
                    fv.current_value = plugin.read_value(
                        self._mem,
                        fv.module_base,
                        fv.field.address.offset,
                        fv.field.type,
                        **kwargs,
                    )
            except OSError:
                log.warning("Lost access to field %s", fv.field.id)
                self._attached = False
                return self._field_values

        return self._field_values

    def write_value(self, field_id: str, value: object) -> None:
        """Immediately write a value to process memory."""
        for fv in self._field_values:
            if fv.field.id != field_id:
                continue

            plugin = self._memory_plugins.get(fv.field.address.method)
            if plugin is None:
                return

            try:
                plugin.write_value(
                    self._mem,
                    fv.module_base,
                    fv.field.address.offset,
                    fv.field.type,
                    value,
                    **_plugin_kwargs(fv.field),
                )
                fv.current_value = value
                if fv.frozen:
                    fv.frozen_value = value
                log.info("Wrote %s = %r", field_id, value)
            except OSError:
                log.exception("Failed to write field %s", field_id)
            return

        log.warning("Field %s not found", field_id)

    def set_frozen(self, field_id: str, frozen: bool) -> None:
        """Toggle freeze for a field."""
        for fv in self._field_values:
            if fv.field.id == field_id:
                fv.frozen = frozen
                fv.frozen_value = fv.current_value if frozen else None
                log.info(
                    "Field %s %s at %r",
                    field_id,
                    "frozen" if frozen else "unfrozen",
                    fv.current_value,
                )
                return

    def is_alive(self) -> bool:
        """Check if the target process still exists."""
        alive = self._mem.is_alive()
        if not alive:
            self._attached = False
        return alive

    def detach(self) -> None:
        """Close memory handle and clean up.

        Restores any active code patches before closing.
        """
        for fv in self._field_values:
            if fv.field.type == "patch" and fv.current_value:
                try:
                    self.toggle_patch(fv.field.id, enable=False)
                except OSError:
                    log.warning(
                        "Could not restore patch %s", fv.field.id
                    )
            fv.frozen = False
            fv.frozen_value = None
        self._mem.close()
        self._attached = False
        log.info("Detached from PID %d", self._pid)
