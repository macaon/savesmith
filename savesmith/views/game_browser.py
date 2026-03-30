"""Game browser page — lists available/installed game definitions."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from savesmith.core.definition import (
    GameDefinition,
    TrainerDefinition,
    load_definition,
)
from savesmith.core.downloader import Downloader

if TYPE_CHECKING:
    from savesmith.window import SaveSmithWindow

log = logging.getLogger(__name__)

_MODE_ICON = {
    "save": "document-save-symbolic",
    "trainer": "system-run-symbolic",
}


def _data_dir() -> Path:
    return Path(GLib.get_user_data_dir()) / "savesmith"


class GameBrowserPage(Adw.NavigationPage):
    def __init__(self, *, window: SaveSmithWindow):
        super().__init__(title="SaveSmith")
        self._window = window
        self._data_dir = _data_dir()
        self._downloader = Downloader(self._data_dir)
        self._definitions: list[GameDefinition | TrainerDefinition] = []

        toolbar_view = Adw.ToolbarView()
        self.set_child(toolbar_view)

        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        # Search toggle in header
        self._search_btn = Gtk.ToggleButton(
            icon_name="system-search-symbolic",
            tooltip_text="Search games",
        )
        self._search_btn.connect("toggled", self._on_search_toggled)
        header.pack_start(self._search_btn)

        # Refresh button
        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Check for updates")
        refresh_btn.connect("clicked", self._on_refresh_clicked)
        header.pack_start(refresh_btn)

        # Primary menu on the right
        menu = Gio.Menu()
        menu.append("Keyboard Shortcuts", "app.shortcuts")
        menu.append("About SaveSmith", "app.about")
        menu_btn = Gtk.MenuButton(
            icon_name="open-menu-symbolic",
            menu_model=menu,
            tooltip_text="Main Menu",
        )
        header.pack_end(menu_btn)

        # Search bar
        self._search_entry = Gtk.SearchEntry(
            placeholder_text="Search games...",
            hexpand=True,
        )
        self._search_entry.connect(
            "search-changed", self._on_search_changed
        )
        self._search_bar = Gtk.SearchBar(child=self._search_entry)
        self._search_bar.connect_entry(self._search_entry)
        self._search_bar.set_key_capture_widget(toolbar_view)
        toolbar_view.add_top_bar(self._search_bar)

        # Main content stack
        self._stack = Gtk.Stack(
            transition_type=Gtk.StackTransitionType.CROSSFADE
        )
        toolbar_view.set_content(self._stack)

        # Empty state
        empty_status = Adw.StatusPage(
            icon_name="applications-games-symbolic",
            title="No Games",
            description="Download game definitions to get started.",
        )
        check_btn = Gtk.Button(
            label="Check for Games",
            halign=Gtk.Align.CENTER,
            css_classes=["suggested-action", "pill"],
        )
        check_btn.connect("clicked", self._on_refresh_clicked)
        empty_status.set_child(check_btn)
        self._stack.add_named(empty_status, "empty")

        # Loading state
        loading_status = Adw.StatusPage(title="Checking for Games...")
        spinner = Adw.Spinner(halign=Gtk.Align.CENTER)
        loading_status.set_child(spinner)
        self._stack.add_named(loading_status, "loading")

        # Fetch failed state
        self._failed_status = Adw.StatusPage(
            icon_name="network-offline-symbolic",
            title="Connection Failed",
            description=(
                "Could not reach GitHub. "
                "Check your connection and try again."
            ),
        )
        retry_btn = Gtk.Button(
            label="Retry",
            halign=Gtk.Align.CENTER,
            css_classes=["pill"],
        )
        retry_btn.connect("clicked", self._on_refresh_clicked)
        self._failed_status.set_child(retry_btn)
        self._stack.add_named(self._failed_status, "failed")

        # No search results
        no_results = Adw.StatusPage(
            icon_name="system-search-symbolic",
            title="No Results",
            description="No games match your search.",
        )
        self._stack.add_named(no_results, "no_results")

        # Game list
        scroll = Gtk.ScrolledWindow(vexpand=True)
        self._list_content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=24,
            margin_bottom=24,
            margin_start=12,
            margin_end=12,
        )
        clamp = Adw.Clamp(
            child=self._list_content, maximum_size=600
        )
        scroll.set_child(clamp)
        self._stack.add_named(scroll, "list")

        # Groups for save editors and trainers
        self._save_group = Adw.PreferencesGroup(title="Save Editors")
        self._trainer_group = Adw.PreferencesGroup(title="Trainers")
        self._list_content.append(self._save_group)
        self._list_content.append(self._trainer_group)

        self._search_query = ""

        # Load any installed definitions on startup
        self._load_installed()

    # -- Search --

    def _on_search_toggled(self, btn: Gtk.ToggleButton) -> None:
        self._search_bar.set_search_mode(btn.get_active())
        if btn.get_active():
            self._search_entry.grab_focus()
        else:
            self._search_entry.set_text("")

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self._search_query = entry.get_text().strip().lower()
        self._rebuild_list()

    # -- Data loading --

    def _load_installed(self) -> None:
        """Load definitions from the local data directory."""
        self._definitions.clear()
        defs_dir = self._data_dir / "definitions"
        if defs_dir.is_dir():
            for path in sorted(defs_dir.glob("*.json")):
                try:
                    defn = load_definition(path)
                    self._definitions.append(defn)
                except Exception:
                    log.exception(
                        "Failed to load definition %s", path.name
                    )

        self._rebuild_list()

    def _rebuild_list(self) -> None:
        """Rebuild the game list UI, filtered by search query."""
        # Clear both groups
        for group in (self._save_group, self._trainer_group):
            while True:
                child = group.get_first_child()
                if child is None:
                    break
                # PreferencesGroup wraps in a listbox; rebuild instead
                break
            parent = group.get_parent()
            if parent is not None:
                parent.remove(group)

        self._save_group = Adw.PreferencesGroup(title="Save Editors")
        self._trainer_group = Adw.PreferencesGroup(title="Trainers")

        if not self._definitions:
            self._stack.set_visible_child_name("empty")
            return

        query = self._search_query
        saves = []
        trainers = []

        for defn in self._definitions:
            if query and query not in defn.name.lower():
                continue
            if isinstance(defn, TrainerDefinition):
                trainers.append(defn)
            else:
                saves.append(defn)

        if not saves and not trainers:
            if query:
                self._stack.set_visible_child_name("no_results")
            else:
                self._stack.set_visible_child_name("empty")
            return

        self._stack.set_visible_child_name("list")

        # Clear and rebuild list_content
        while self._list_content.get_first_child():
            self._list_content.remove(
                self._list_content.get_first_child()
            )

        if saves:
            self._save_group = Adw.PreferencesGroup(
                title="Save Editors"
            )
            for defn in saves:
                self._save_group.add(self._make_row(defn))
            self._list_content.append(self._save_group)

        if trainers:
            self._trainer_group = Adw.PreferencesGroup(
                title="Trainers"
            )
            for defn in trainers:
                self._trainer_group.add(self._make_row(defn))
            self._list_content.append(self._trainer_group)

    def _make_row(
        self, defn: GameDefinition | TrainerDefinition
    ) -> Adw.ActionRow:
        is_trainer = isinstance(defn, TrainerDefinition)
        mode = "trainer" if is_trainer else "save"

        subtitle = (
            f"{len(defn.fields)} fields"
            if is_trainer
            else f"{len(defn.fields)} editable fields"
        )

        row = Adw.ActionRow(
            title=defn.name,
            subtitle=subtitle,
            activatable=True,
        )

        # Mode icon as prefix
        icon = Gtk.Image(
            icon_name=_MODE_ICON.get(mode, "applications-games-symbolic"),
            pixel_size=24,
        )
        row.add_prefix(icon)

        row.add_suffix(
            Gtk.Image(icon_name="go-next-symbolic")
        )
        row.connect("activated", self._on_game_activated, defn)
        return row

    # -- Refresh / download --

    def _on_refresh_clicked(self, _btn) -> None:
        self._stack.set_visible_child_name("loading")

        def do_fetch():
            manifest = self._downloader.fetch_manifest()
            if manifest is None:
                GLib.idle_add(self._on_fetch_failed)
                return

            for entry in self._downloader.list_definitions():
                self._downloader.download_definition_with_deps(
                    entry["path"]
                )

            GLib.idle_add(self._on_fetch_complete)

        thread = threading.Thread(target=do_fetch, daemon=True)
        thread.start()

    def _on_fetch_complete(self) -> None:
        self._load_installed()
        if not self._definitions:
            self._stack.set_visible_child_name("empty")

    def _on_fetch_failed(self) -> None:
        self._stack.set_visible_child_name("failed")

    # -- Navigation --

    def _on_game_activated(
        self, _row, defn: GameDefinition | TrainerDefinition
    ) -> None:
        if isinstance(defn, TrainerDefinition):
            self._activate_trainer(defn)
        else:
            from savesmith.views.save_browser import SaveBrowserPage

            page = SaveBrowserPage(
                window=self._window, definition=defn
            )
            self._window.nav_view.push(page)

    def _activate_trainer(self, defn: TrainerDefinition) -> None:
        self._stack.set_visible_child_name("loading")

        def do_scan():
            from savesmith.core.process import find_processes

            return find_processes(defn.process_name)

        def on_done(processes):
            self._rebuild_list()

            if not processes:
                self._window.add_toast(
                    Adw.Toast(
                        title=f"{defn.process_name} is not running"
                    )
                )
                return

            if len(processes) == 1:
                from savesmith.views.trainer_editor import (
                    TrainerEditorPage,
                )

                page = TrainerEditorPage(
                    window=self._window,
                    definition=defn,
                    pid=processes[0].pid,
                )
                self._window.nav_view.push(page)
            else:
                from savesmith.views.process_picker import (
                    ProcessPickerPage,
                )

                page = ProcessPickerPage(
                    window=self._window, definition=defn
                )
                self._window.nav_view.push(page)

        def thread_target():
            processes = do_scan()
            GLib.idle_add(on_done, processes)

        thread = threading.Thread(target=thread_target, daemon=True)
        thread.start()
