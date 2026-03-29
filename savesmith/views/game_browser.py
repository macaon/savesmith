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

from savesmith.core.definition import GameDefinition
from savesmith.core.downloader import Downloader

if TYPE_CHECKING:
    from savesmith.window import SaveSmithWindow

log = logging.getLogger(__name__)


def _data_dir() -> Path:
    return Path(GLib.get_user_data_dir()) / "savesmith"


class GameBrowserPage(Adw.NavigationPage):
    def __init__(self, *, window: SaveSmithWindow):
        super().__init__(title="SaveSmith")
        self._window = window
        self._data_dir = _data_dir()
        self._downloader = Downloader(self._data_dir)
        self._definitions: list[GameDefinition] = []

        toolbar_view = Adw.ToolbarView()
        self.set_child(toolbar_view)

        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        # Refresh button on the left
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

        # Main content stack
        self._stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
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
        spinner = Gtk.Spinner(spinning=True, halign=Gtk.Align.CENTER)
        loading_status.set_child(spinner)
        self._stack.add_named(loading_status, "loading")

        # Fetch failed state
        self._failed_status = Adw.StatusPage(
            icon_name="network-offline-symbolic",
            title="Connection Failed",
            description="Could not reach GitHub. Check your connection and try again.",
        )
        retry_btn = Gtk.Button(
            label="Retry",
            halign=Gtk.Align.CENTER,
            css_classes=["pill"],
        )
        retry_btn.connect("clicked", self._on_refresh_clicked)
        self._failed_status.set_child(retry_btn)
        self._stack.add_named(self._failed_status, "failed")

        # Game list
        scroll = Gtk.ScrolledWindow(vexpand=True)
        self._list_box = Gtk.ListBox(
            selection_mode=Gtk.SelectionMode.NONE,
            css_classes=["boxed-list"],
            margin_top=24,
            margin_bottom=24,
            margin_start=12,
            margin_end=12,
        )
        clamp = Adw.Clamp(child=self._list_box, maximum_size=600)
        scroll.set_child(clamp)
        self._stack.add_named(scroll, "list")

        # Load any installed definitions on startup
        self._load_installed()

    def _load_installed(self) -> None:
        """Load definitions from the local data directory."""
        self._definitions.clear()
        defs_dir = self._data_dir / "definitions"
        if defs_dir.is_dir():
            for path in sorted(defs_dir.glob("*.json")):
                try:
                    defn = GameDefinition.from_file(path)
                    self._definitions.append(defn)
                except Exception:
                    log.exception("Failed to load definition %s", path.name)

        self._rebuild_list()

    def _rebuild_list(self) -> None:
        """Rebuild the game list UI."""
        while True:
            row = self._list_box.get_row_at_index(0)
            if row is None:
                break
            self._list_box.remove(row)

        if not self._definitions:
            self._stack.set_visible_child_name("empty")
            return

        self._stack.set_visible_child_name("list")
        for defn in self._definitions:
            row = Adw.ActionRow(
                title=defn.name,
                subtitle=f"{len(defn.fields)} editable fields",
                activatable=True,
            )
            row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            row.connect("activated", self._on_game_activated, defn)
            self._list_box.append(row)

    def _on_refresh_clicked(self, _btn) -> None:
        self._stack.set_visible_child_name("loading")

        def do_fetch():
            manifest = self._downloader.fetch_manifest()
            if manifest is None:
                GLib.idle_add(self._on_fetch_failed)
                return

            for entry in self._downloader.list_definitions():
                self._downloader.download_definition_with_deps(entry["path"])

            GLib.idle_add(self._on_fetch_complete)

        thread = threading.Thread(target=do_fetch, daemon=True)
        thread.start()

    def _on_fetch_complete(self) -> None:
        self._load_installed()
        if not self._definitions:
            self._stack.set_visible_child_name("empty")

    def _on_fetch_failed(self) -> None:
        self._stack.set_visible_child_name("failed")

    def _on_game_activated(self, _row, defn: GameDefinition) -> None:
        from savesmith.views.save_browser import SaveBrowserPage

        page = SaveBrowserPage(window=self._window, definition=defn)
        self._window.nav_view.push(page)
