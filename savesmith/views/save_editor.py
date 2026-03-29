"""Save editor page — edit field values grouped by category."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from savesmith.core.definition import GameDefinition
from savesmith.core.editor import FieldValue, SaveEditor
from savesmith.core.plugin_loader import PluginLoader
from savesmith.core.save_file import SaveFile

if TYPE_CHECKING:
    from savesmith.window import SaveSmithWindow

log = logging.getLogger(__name__)


def _data_dir() -> Path:
    return Path(GLib.get_user_data_dir()) / "savesmith"


class SaveEditorPage(Adw.NavigationPage):
    def __init__(
        self,
        *,
        window: SaveSmithWindow,
        definition: GameDefinition,
        save_path: Path,
    ):
        super().__init__(title=save_path.stem)
        self._window = window
        self._definition = definition
        self._save_path = save_path
        self._editor: SaveEditor | None = None
        self._widgets: dict[str, Gtk.Widget] = {}
        self._populating = False  # Suppress signals during widget setup

        toolbar_view = Adw.ToolbarView()
        self.set_child(toolbar_view)

        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        # Revert on the left
        self._revert_btn = Gtk.Button(
            label="Revert",
            tooltip_text="Revert Changes",
            sensitive=False,
        )
        self._revert_btn.connect("clicked", self._on_revert_clicked)
        header.pack_start(self._revert_btn)

        # Save on the right (no suggested-action in header bars per HIG)
        self._save_btn = Gtk.Button(
            label="Save",
            tooltip_text="Save Changes",
            sensitive=False,
        )
        self._save_btn.connect("clicked", self._on_save_clicked)
        header.pack_end(self._save_btn)

        # Content stack
        self._stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        toolbar_view.set_content(self._stack)

        # Loading state
        loading = Adw.StatusPage(title="Loading save...")
        spinner = Gtk.Spinner(spinning=True, halign=Gtk.Align.CENTER)
        loading.set_child(spinner)
        self._stack.add_named(loading, "loading")

        # Error state
        self._error_status = Adw.StatusPage(
            icon_name="dialog-error-symbolic",
            title="Error",
        )
        self._stack.add_named(self._error_status, "error")

        # Editor content
        scroll = Gtk.ScrolledWindow(vexpand=True)
        self._content_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=24,
            margin_top=24,
            margin_bottom=24,
            margin_start=12,
            margin_end=12,
        )
        clamp = Adw.Clamp(child=self._content_box, maximum_size=600)
        scroll.set_child(clamp)
        self._stack.add_named(scroll, "editor")

        self._stack.set_visible_child_name("loading")
        GLib.idle_add(self._load_save)

    def _load_save(self) -> None:
        try:
            data_dir = _data_dir()

            loader = PluginLoader(data_dir)
            loader.load_all()

            met, missing = loader.has_requirements(self._definition.requires)
            if not met:
                self._show_error(f"Missing plugins: {', '.join(missing)}")
                return

            format_plugins = []
            for fmt_id in self._definition.save_format_pipeline:
                plugin = loader.get_format(fmt_id)
                if plugin is None:
                    self._show_error(f"Format plugin {fmt_id!r} not loaded")
                    return
                format_plugins.append(plugin)

            save_file = SaveFile(self._save_path, format_plugins)
            save_file.load()

            self._editor = SaveEditor(
                save_file, self._definition, loader.search_plugins
            )
            field_values = self._editor.read_fields()

            self._build_editor_ui(field_values)
            self._stack.set_visible_child_name("editor")

        except Exception as e:
            log.exception("Failed to load save")
            self._show_error(str(e))

        return False

    def _show_error(self, message: str) -> None:
        self._error_status.set_description(message)
        self._stack.set_visible_child_name("error")

    def _build_editor_ui(self, field_values: list[FieldValue]) -> None:
        self._populating = True

        categories: dict[str, list[FieldValue]] = {}
        for fv in field_values:
            categories.setdefault(fv.field.category, []).append(fv)

        for cat_name, fvs in categories.items():
            group = Adw.PreferencesGroup(title=cat_name)
            for fv in fvs:
                row = self._create_field_row(fv)
                if row is not None:
                    group.add(row)
            self._content_box.append(group)

        self._populating = False

    def _create_field_row(self, fv: FieldValue) -> Gtk.Widget | None:
        widget_type = fv.field.widget

        if widget_type == "spin":
            return self._create_spin_row(fv)
        elif widget_type == "switch":
            return self._create_switch_row(fv)
        elif widget_type == "entry":
            return self._create_entry_row(fv)
        else:
            log.warning("Unknown widget type %r for field %s", widget_type, fv.field.id)
            return None

    def _create_spin_row(self, fv: FieldValue) -> Adw.SpinRow:
        adj = Gtk.Adjustment(
            value=float(fv.current_value),
            lower=fv.field.min if fv.field.min is not None else -999999999,
            upper=fv.field.max if fv.field.max is not None else 999999999,
            step_increment=fv.field.step if fv.field.step is not None else 1,
            page_increment=(fv.field.step or 1) * 10,
        )
        row = Adw.SpinRow(
            title=fv.field.name,
            adjustment=adj,
        )
        row.set_digits(2 if fv.field.type == "float32" else 0)
        row.connect("changed", self._on_spin_changed, fv.field.id)
        self._widgets[fv.field.id] = row
        return row

    def _create_switch_row(self, fv: FieldValue) -> Adw.SwitchRow:
        row = Adw.SwitchRow(
            title=fv.field.name,
            active=bool(fv.current_value),
        )
        row.connect("notify::active", self._on_switch_toggled, fv.field.id)
        self._widgets[fv.field.id] = row
        return row

    def _create_entry_row(self, fv: FieldValue) -> Adw.EntryRow:
        row = Adw.EntryRow(title=fv.field.name)
        row.set_text(str(fv.current_value) if fv.current_value else "")
        row.connect("changed", self._on_entry_changed, fv.field.id)
        self._widgets[fv.field.id] = row
        return row

    def _on_spin_changed(self, row: Adw.SpinRow, field_id: str) -> None:
        if self._populating or not self._editor:
            return
        self._editor.set_value(field_id, row.get_value())
        self._update_button_sensitivity()

    def _on_switch_toggled(self, row: Adw.SwitchRow, _pspec, field_id: str) -> None:
        if self._populating or not self._editor:
            return
        self._editor.set_value(field_id, row.get_active())
        self._update_button_sensitivity()

    def _on_entry_changed(self, row: Adw.EntryRow, field_id: str) -> None:
        if self._populating or not self._editor:
            return
        self._editor.set_value(field_id, row.get_text())
        self._update_button_sensitivity()

    def _update_button_sensitivity(self) -> None:
        has_changes = self._editor.has_changes if self._editor else False
        self._save_btn.set_sensitive(has_changes)
        self._revert_btn.set_sensitive(has_changes)

    def _on_save_clicked(self, _btn) -> None:
        if self._editor is None:
            return

        try:
            self._editor.save(backup=True)
            self._update_button_sensitivity()
            self._window.add_toast(
                Adw.Toast(title="Save file updated successfully")
            )
        except Exception as e:
            log.exception("Failed to save")
            dialog = Adw.AlertDialog(
                heading="Save Failed",
                body=str(e),
            )
            dialog.add_response("ok", "OK")
            dialog.present(self._window)

    def _on_revert_clicked(self, _btn) -> None:
        if self._editor is None:
            return

        self._editor.revert()

        self._populating = True
        for fv in self._editor.field_values:
            widget = self._widgets.get(fv.field.id)
            if widget is None:
                continue

            if isinstance(widget, Adw.SpinRow):
                widget.set_value(float(fv.current_value))
            elif isinstance(widget, Adw.SwitchRow):
                widget.set_active(bool(fv.current_value))
            elif isinstance(widget, Adw.EntryRow):
                widget.set_text(str(fv.current_value) if fv.current_value else "")

        self._populating = False
        self._update_button_sensitivity()
