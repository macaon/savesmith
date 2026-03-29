"""Edit engine — reads field values from save data and applies modifications."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from savesmith.core.definition import FieldDef, GameDefinition
from savesmith.core.save_file import SaveFile

log = logging.getLogger(__name__)


@dataclass
class FieldValue:
    """A field's current state in the editor."""

    field: FieldDef
    offset: int  # Byte offset in decompressed data where the value lives
    original_value: object
    current_value: object

    @property
    def is_modified(self) -> bool:
        return self.current_value != self.original_value


class SaveEditor:
    """Reads and edits field values in a loaded save file."""

    def __init__(
        self,
        save_file: SaveFile,
        definition: GameDefinition,
        search_plugins: dict[str, object],
    ):
        self._save = save_file
        self._definition = definition
        self._search_plugins = search_plugins
        self._field_values: list[FieldValue] = []

    @property
    def field_values(self) -> list[FieldValue]:
        return list(self._field_values)

    @property
    def has_changes(self) -> bool:
        return any(fv.is_modified for fv in self._field_values)

    def read_fields(self) -> list[FieldValue]:
        """Read all field values from the save data."""
        self._field_values = []
        data = self._save.data

        for field_def in self._definition.fields:
            search_plugin = self._search_plugins.get(field_def.search.method)
            if search_plugin is None:
                log.warning(
                    "No search plugin %r for field %s — skipping",
                    field_def.search.method,
                    field_def.id,
                )
                continue

            try:
                offset, value = search_plugin.find_field(
                    data, field_def.type, **field_def.search.params
                )
                self._field_values.append(
                    FieldValue(
                        field=field_def,
                        offset=offset,
                        original_value=value,
                        current_value=value,
                    )
                )
                log.debug(
                    "Field %s: offset=%d, value=%r",
                    field_def.id,
                    offset,
                    value,
                )
            except Exception:
                log.exception("Failed to read field %s", field_def.id)

        return self._field_values

    def set_value(self, field_id: str, value: object) -> None:
        """Update a field's current value (not yet written to save)."""
        for fv in self._field_values:
            if fv.field.id == field_id:
                fv.current_value = value
                return
        log.warning("Field %s not found", field_id)

    def apply_changes(self) -> None:
        """Write all modified values back into the save data buffer."""
        data = self._save.data

        for fv in self._field_values:
            if not fv.is_modified:
                continue

            search_plugin = self._search_plugins.get(fv.field.search.method)
            if search_plugin is None:
                continue

            try:
                data = search_plugin.write_field(
                    data, fv.offset, fv.field.type, fv.current_value
                )
                log.info(
                    "Applied %s: %r → %r",
                    fv.field.id,
                    fv.original_value,
                    fv.current_value,
                )
            except Exception:
                log.exception("Failed to write field %s", fv.field.id)

        self._save.data = data

    def revert(self) -> None:
        """Reset all current values back to their originals."""
        for fv in self._field_values:
            fv.current_value = fv.original_value

    def save(self, backup: bool = True) -> None:
        """Apply changes and write the save file."""
        self.apply_changes()
        self._save.save(backup=backup)

        # Update originals to reflect saved state
        for fv in self._field_values:
            fv.original_value = fv.current_value
