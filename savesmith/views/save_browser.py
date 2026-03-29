"""Save browser page — lists save files found in a user-chosen folder."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from savesmith.core.definition import GameDefinition

if TYPE_CHECKING:
    from savesmith.window import SaveSmithWindow

log = logging.getLogger(__name__)


class SaveBrowserPage(Adw.NavigationPage):
    def __init__(self, *, window: SaveSmithWindow, definition: GameDefinition):
        super().__init__(title=definition.name)
        self._window = window
        self._definition = definition
        self._save_dir: Path | None = None

        toolbar_view = Adw.ToolbarView()
        self.set_child(toolbar_view)

        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        # Open folder button in header
        open_btn = Gtk.Button(icon_name="folder-open-symbolic")
        open_btn.set_tooltip_text("Open Save Folder")
        open_btn.connect("clicked", self._on_open_folder)
        header.pack_start(open_btn)

        self._stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        toolbar_view.set_content(self._stack)

        # Empty state — prompt to open folder
        status = Adw.StatusPage(
            icon_name="folder-open-symbolic",
            title="Open Save Folder",
            description="Browse to the folder containing your save files.",
        )
        browse_btn = Gtk.Button(
            label="Open Folder",
            halign=Gtk.Align.CENTER,
            css_classes=["suggested-action", "pill"],
        )
        browse_btn.connect("clicked", self._on_open_folder)
        status.set_child(browse_btn)
        self._stack.add_named(status, "empty")

        # Save list
        scroll = Gtk.ScrolledWindow(vexpand=True)
        list_content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=24,
            margin_bottom=24,
            margin_start=12,
            margin_end=12,
        )

        # Folder info row
        folder_group = Adw.PreferencesGroup()
        self._folder_row = Adw.ActionRow(
            title="Save Folder",
            subtitle="No folder selected",
        )
        folder_btn = Gtk.Button(
            icon_name="folder-open-symbolic",
            valign=Gtk.Align.CENTER,
        )
        folder_btn.set_tooltip_text("Change Folder")
        folder_btn.connect("clicked", self._on_open_folder)
        self._folder_row.add_suffix(folder_btn)
        folder_group.add(self._folder_row)
        list_content.append(folder_group)

        # Save file list
        self._saves_group = Adw.PreferencesGroup(title="Save Files")
        list_content.append(self._saves_group)

        clamp = Adw.Clamp(child=list_content, maximum_size=600)
        scroll.set_child(clamp)
        self._stack.add_named(scroll, "list")

        # No saves found
        no_saves = Adw.StatusPage(
            icon_name="folder-symbolic",
            title="No Saves Found",
            description="No matching save files were found in this folder.",
        )
        retry_btn = Gtk.Button(
            label="Try Another Folder",
            halign=Gtk.Align.CENTER,
            css_classes=["pill"],
        )
        retry_btn.connect("clicked", self._on_open_folder)
        no_saves.set_child(retry_btn)
        self._stack.add_named(no_saves, "no_saves")

        self._stack.set_visible_child_name("empty")

    def _on_open_folder(self, _btn) -> None:
        dialog = Gtk.FileDialog(title="Select Save Folder")
        dialog.select_folder(self._window, None, self._on_folder_chosen)

    def _on_folder_chosen(self, dialog, result) -> None:
        try:
            folder = dialog.select_folder_finish(result)
        except GLib.Error:
            return

        self._save_dir = Path(folder.get_path())
        self._folder_row.set_subtitle(str(self._save_dir))
        self._scan_saves()

    def _scan_saves(self) -> None:
        """Scan the selected folder for save files matching the definition glob."""
        if self._save_dir is None:
            return

        # Clear existing save rows from the group
        while True:
            child = self._saves_group.get_first_child()
            if child is None:
                break
            # PreferencesGroup wraps rows in a listbox, so we need to iterate properly
            break

        # Rebuild the saves group
        parent = self._saves_group.get_parent()
        if parent is not None:
            box = parent
            box.remove(self._saves_group)
            self._saves_group = Adw.PreferencesGroup(title="Save Files")
            box.append(self._saves_group)

        save_files = sorted(self._save_dir.glob(self._definition.save_glob))

        if not save_files:
            self._stack.set_visible_child_name("no_saves")
            return

        self._stack.set_visible_child_name("list")

        for save_path in save_files:
            meta = self._load_meta(save_path)
            title = meta.get("name", save_path.stem) if meta else save_path.stem
            subtitle = ""
            if meta:
                date = meta.get("lastPlayedDate", "")
                if date:
                    subtitle = date[:19].replace("T", " ")

            row = Adw.ActionRow(
                title=title,
                subtitle=subtitle,
                activatable=True,
            )
            row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            row.connect("activated", self._on_save_activated, save_path)
            self._saves_group.add(row)

    def _load_meta(self, save_path: Path) -> dict | None:
        """Try to load the .meta sidecar file for a save."""
        if self._definition.meta_glob is None:
            return None

        meta_path = save_path.with_suffix(save_path.suffix + ".meta")
        if meta_path.exists():
            try:
                return json.loads(meta_path.read_text())
            except Exception:
                log.debug("Could not parse meta file %s", meta_path)
        return None

    def _on_save_activated(self, _row, save_path: Path) -> None:
        from savesmith.views.save_editor import SaveEditorPage

        page = SaveEditorPage(
            window=self._window,
            definition=self._definition,
            save_path=save_path,
        )
        self._window.nav_view.push(page)
