"""Trainer editor page — live process memory editing with freeze toggles."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, GObject, Gtk

from savesmith.core.definition import TrainerDefinition
from savesmith.core.plugin_loader import PluginLoader
from savesmith.core.trainer import TrainerEditor, TrainerFieldValue

if TYPE_CHECKING:
    from savesmith.window import SaveSmithWindow

log = logging.getLogger(__name__)


def _data_dir() -> Path:
    return Path(GLib.get_user_data_dir()) / "savesmith"


class TrainerEditorPage(Adw.NavigationPage):
    def __init__(
        self,
        *,
        window: SaveSmithWindow,
        definition: TrainerDefinition,
        pid: int,
    ):
        super().__init__(title=f"{definition.name} — PID {pid}")
        self._window = window
        self._definition = definition
        self._pid = pid
        self._trainer: TrainerEditor | None = None
        self._widgets: dict[str, Gtk.Widget] = {}
        self._apply_btns: dict[str, Gtk.Button] = {}
        self._freeze_toggles: dict[str, Gtk.ToggleButton] = {}
        self._signal_ids: dict[str, tuple[Gtk.Widget, int]] = {}
        self._poll_source_id: int | None = None

        toolbar_view = Adw.ToolbarView()
        self.set_child(toolbar_view)

        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        # Detach button
        detach_btn = Gtk.Button(
            label="Detach",
            tooltip_text="Stop trainer and go back",
        )
        detach_btn.connect("clicked", self._on_detach)
        header.pack_start(detach_btn)

        # Status label
        self._status_label = Gtk.Label(
            label="Attaching...",
            css_classes=["dim-label"],
        )
        header.pack_end(self._status_label)

        # Content stack
        self._stack = Gtk.Stack(
            transition_type=Gtk.StackTransitionType.CROSSFADE
        )
        toolbar_view.set_content(self._stack)

        # Loading state
        loading = Adw.StatusPage(title="Attaching to process...")
        spinner = Adw.Spinner(halign=Gtk.Align.CENTER)
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

        # Clean up on destroy
        self.connect("destroy", self._on_destroy)

        thread = threading.Thread(
            target=self._attach_worker, daemon=True
        )
        thread.start()

    def _attach_worker(self) -> None:
        """Run the attach sequence in a background thread."""
        try:
            data_dir = _data_dir()
            loader = PluginLoader(data_dir)
            loader.load_all()

            met, missing = loader.has_requirements(
                self._definition.requires
            )
            if not met:
                GLib.idle_add(
                    self._show_error,
                    f"Missing plugins: {', '.join(missing)}",
                )
                return

            trainer = TrainerEditor(
                self._pid,
                self._definition,
                loader.memory_plugins,
            )
            trainer.attach()
            field_values = trainer.read_fields()

            if not field_values:
                GLib.idle_add(
                    self._show_error,
                    "No fields could be read. The module may not be "
                    "loaded yet — try again once the game is fully "
                    "started.",
                )
                return

            GLib.idle_add(self._on_attached, trainer, field_values)

        except PermissionError as e:
            GLib.idle_add(self._show_error, str(e))
        except ProcessLookupError as e:
            GLib.idle_add(self._show_error, str(e))
        except Exception as e:
            log.exception("Failed to attach")
            GLib.idle_add(self._show_error, str(e))

    def _on_attached(self, trainer, field_values):
        """Called on the main thread once attach succeeds."""
        self._trainer = trainer
        self._build_editor_ui(field_values)
        self._status_label.set_label(f"PID {self._pid} — Attached")
        self._stack.set_visible_child_name("editor")

        self._poll_source_id = GLib.timeout_add(
            self._definition.poll_interval_ms, self._on_poll
        )
        return False

    def _show_error(self, message: str) -> None:
        self._error_status.set_description(message)
        self._stack.set_visible_child_name("error")
        self._status_label.set_label("Error")

    def _build_editor_ui(
        self, field_values: list[TrainerFieldValue]
    ) -> None:
        categories: dict[str, list[TrainerFieldValue]] = {}
        for fv in field_values:
            categories.setdefault(fv.field.category, []).append(fv)

        for cat_name, fvs in categories.items():
            group = Adw.PreferencesGroup(title=cat_name)
            for fv in fvs:
                row = self._create_field_row(fv)
                if row is not None:
                    group.add(row)
            self._content_box.append(group)

    def _create_field_row(
        self, fv: TrainerFieldValue
    ) -> Gtk.Widget | None:
        widget_type = fv.field.widget

        # Skip fields with null pointer chains (system not installed)
        if fv.current_value is None:
            row = Adw.ActionRow(
                title=fv.field.name,
                subtitle="Unavailable",
                sensitive=False,
            )
            self._widgets[fv.field.id] = row
            return row

        if fv.field.type == "patch":
            row = self._create_patch_row(fv)
        elif widget_type == "spin":
            row = self._create_spin_row(fv)
        elif widget_type == "switch":
            row = self._create_switch_row(fv)
        elif widget_type == "entry":
            row = self._create_entry_row(fv)
        else:
            log.warning(
                "Unknown widget type %r for field %s",
                widget_type,
                fv.field.id,
            )
            return None

        # Add apply button for spin/entry (not switch — those are
        # immediate)
        if widget_type in ("spin", "entry") and row is not None:
            apply_btn = Gtk.Button(
                icon_name="object-select-symbolic",
                valign=Gtk.Align.CENTER,
                tooltip_text="Write value to game",
                css_classes=["flat"],
                sensitive=False,
            )
            apply_btn.connect(
                "clicked", self._on_apply_clicked, fv.field.id
            )
            row.add_suffix(apply_btn)
            self._apply_btns[fv.field.id] = apply_btn

        # Add freeze toggle if the field is freezable
        if fv.field.freezable and row is not None:
            freeze_btn = Gtk.ToggleButton(
                icon_name="changes-prevent-symbolic",
                valign=Gtk.Align.CENTER,
                tooltip_text="Freeze value",
                css_classes=["flat"],
            )
            freeze_btn.connect(
                "toggled", self._on_freeze_toggled, fv.field.id
            )
            row.add_suffix(freeze_btn)
            self._freeze_toggles[fv.field.id] = freeze_btn

        return row

    def _create_spin_row(self, fv: TrainerFieldValue) -> Adw.SpinRow:
        adj = Gtk.Adjustment(
            value=float(fv.current_value)
            if fv.current_value is not None
            else 0,
            lower=fv.field.min if fv.field.min is not None else -999999999,
            upper=fv.field.max if fv.field.max is not None else 999999999,
            step_increment=fv.field.step
            if fv.field.step is not None
            else 1,
            page_increment=(fv.field.step or 1) * 10,
        )
        row = Adw.SpinRow(
            title=fv.field.name,
            adjustment=adj,
        )
        row.set_digits(2 if fv.field.type == "float32" else 0)
        sig = row.connect("changed", self._on_value_edited, fv.field.id)
        self._widgets[fv.field.id] = row
        self._signal_ids[fv.field.id] = (row, sig)
        return row

    def _create_switch_row(
        self, fv: TrainerFieldValue
    ) -> Adw.SwitchRow:
        row = Adw.SwitchRow(
            title=fv.field.name,
            active=bool(fv.current_value),
        )
        sig = row.connect(
            "notify::active", self._on_switch_toggled, fv.field.id
        )
        self._widgets[fv.field.id] = row
        self._signal_ids[fv.field.id] = (row, sig)
        return row

    def _create_patch_row(
        self, fv: TrainerFieldValue
    ) -> Adw.SwitchRow:
        row = Adw.SwitchRow(
            title=fv.field.name,
            active=bool(fv.current_value),
        )
        sig = row.connect(
            "notify::active", self._on_patch_toggled, fv.field.id
        )
        self._widgets[fv.field.id] = row
        self._signal_ids[fv.field.id] = (row, sig)
        return row

    def _create_entry_row(self, fv: TrainerFieldValue) -> Adw.EntryRow:
        row = Adw.EntryRow(title=fv.field.name)
        row.set_text(
            str(fv.current_value) if fv.current_value else ""
        )
        sig = row.connect(
            "changed", self._on_value_edited, fv.field.id
        )
        self._widgets[fv.field.id] = row
        self._signal_ids[fv.field.id] = (row, sig)
        return row

    # -- Value change handlers --

    def _on_patch_toggled(
        self, row: Adw.SwitchRow, _pspec, field_id: str
    ) -> None:
        """Toggle a code patch on/off."""
        if not self._trainer:
            return
        self._trainer.toggle_patch(field_id, row.get_active())

    def _on_value_edited(self, _widget, field_id: str) -> None:
        """User edited a spin/entry — enable the apply button."""
        apply_btn = self._apply_btns.get(field_id)
        if apply_btn:
            apply_btn.set_sensitive(True)

    def _on_apply_clicked(self, _btn, field_id: str) -> None:
        """Write the current widget value to process memory."""
        if not self._trainer:
            return

        widget = self._widgets.get(field_id)
        if widget is None:
            return

        if isinstance(widget, Adw.SpinRow):
            value = widget.get_value()
        elif isinstance(widget, Adw.EntryRow):
            value = widget.get_text()
        else:
            return

        self._trainer.write_value(field_id, value)

        apply_btn = self._apply_btns.get(field_id)
        if apply_btn:
            apply_btn.set_sensitive(False)

        self._window.add_toast(
            Adw.Toast(title=f"{field_id} written", timeout=1)
        )

    def _on_switch_toggled(
        self, row: Adw.SwitchRow, _pspec, field_id: str
    ) -> None:
        """Switches write immediately — no apply button needed."""
        if not self._trainer:
            return
        self._trainer.write_value(field_id, row.get_active())

    def _on_freeze_toggled(
        self, btn: Gtk.ToggleButton, field_id: str
    ) -> None:
        if not self._trainer:
            return
        self._trainer.set_frozen(field_id, btn.get_active())

    # -- Polling --

    def _on_poll(self) -> bool:
        """Called on a timer to refresh field values from memory."""
        if not self._trainer or not self._trainer.is_alive():
            self._on_process_lost()
            return GLib.SOURCE_REMOVE

        field_values = self._trainer.poll()

        if not self._trainer.attached:
            self._on_process_lost()
            return GLib.SOURCE_REMOVE

        for fv in field_values:
            sig_info = self._signal_ids.get(fv.field.id)
            if sig_info is None:
                continue
            widget, sig_id = sig_info

            # Don't overwrite a field the user is editing
            apply_btn = self._apply_btns.get(fv.field.id)
            if apply_btn and apply_btn.get_sensitive():
                continue

            GObject.signal_handler_block(widget, sig_id)
            try:
                if isinstance(widget, Adw.SpinRow):
                    widget.set_value(float(fv.current_value))
                elif isinstance(widget, Adw.SwitchRow):
                    widget.set_active(bool(fv.current_value))
                elif isinstance(widget, Adw.EntryRow):
                    widget.set_text(
                        str(fv.current_value)
                        if fv.current_value
                        else ""
                    )
            finally:
                GObject.signal_handler_unblock(widget, sig_id)

        return GLib.SOURCE_CONTINUE

    def _on_process_lost(self) -> None:
        """Handle the target process dying."""
        self._stop_polling()
        if self._trainer:
            self._trainer.detach()
        self._status_label.set_label("Process Lost")
        self._window.add_toast(
            Adw.Toast(title="Target process has exited")
        )

    # -- Lifecycle --

    def _on_detach(self, _btn=None) -> None:
        self._stop_polling()
        if self._trainer:
            self._trainer.detach()
        self._window.nav_view.pop()

    def _stop_polling(self) -> None:
        if self._poll_source_id is not None:
            GLib.source_remove(self._poll_source_id)
            self._poll_source_id = None

    def _on_destroy(self, _widget) -> None:
        self._stop_polling()
        if self._trainer:
            self._trainer.detach()
