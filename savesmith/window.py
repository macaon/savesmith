"""Main application window."""

from __future__ import annotations

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

log = logging.getLogger(__name__)


class SaveSmithWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(
            title="SaveSmith",
            default_width=800,
            default_height=600,
            **kwargs,
        )

        self._toast_overlay = Adw.ToastOverlay()
        self._nav_view = Adw.NavigationView()
        self._toast_overlay.set_child(self._nav_view)
        self.set_content(self._toast_overlay)

        # Start with the game browser page
        from savesmith.views.game_browser import GameBrowserPage

        page = GameBrowserPage(window=self)
        self._nav_view.push(page)

    @property
    def nav_view(self) -> Adw.NavigationView:
        return self._nav_view

    def add_toast(self, toast: Adw.Toast) -> None:
        self._toast_overlay.add_toast(toast)
