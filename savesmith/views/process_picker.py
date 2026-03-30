"""Process picker page — select a running process to attach the trainer to."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from savesmith.core.definition import TrainerDefinition
from savesmith.core.process import find_processes

if TYPE_CHECKING:
    from savesmith.window import SaveSmithWindow

log = logging.getLogger(__name__)


class ProcessPickerPage(Adw.NavigationPage):
    def __init__(self, *, window: SaveSmithWindow, definition: TrainerDefinition):
        super().__init__(title=definition.name)
        self._window = window
        self._definition = definition

        toolbar_view = Adw.ToolbarView()
        self.set_child(toolbar_view)

        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Rescan for processes")
        refresh_btn.connect("clicked", self._on_refresh)
        header.pack_start(refresh_btn)

        self._stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        toolbar_view.set_content(self._stack)

        # Empty state — no process found
        empty = Adw.StatusPage(
            icon_name="system-run-symbolic",
            title="No Process Found",
            description=f"Start {definition.process_name} and click Scan.",
        )
        scan_btn = Gtk.Button(
            label="Scan for Process",
            halign=Gtk.Align.CENTER,
            css_classes=["suggested-action", "pill"],
        )
        scan_btn.connect("clicked", self._on_refresh)
        empty.set_child(scan_btn)
        self._stack.add_named(empty, "empty")

        # Process list
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

        self._stack.set_visible_child_name("empty")
        self._scan()

    def _on_refresh(self, _btn=None) -> None:
        self._scan()

    def _scan(self) -> None:
        """Scan for matching processes and rebuild the list."""
        while True:
            row = self._list_box.get_row_at_index(0)
            if row is None:
                break
            self._list_box.remove(row)

        processes = find_processes(self._definition.process_name)

        if not processes:
            self._stack.set_visible_child_name("empty")
            return

        self._stack.set_visible_child_name("list")
        for proc in processes:
            cmdline_short = proc.cmdline[:80]
            if len(proc.cmdline) > 80:
                cmdline_short += "..."
            row = Adw.ActionRow(
                title=f"{proc.name} (PID {proc.pid})",
                subtitle=cmdline_short,
                activatable=True,
            )
            row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            row.connect("activated", self._on_process_activated, proc.pid)
            self._list_box.append(row)

    def _on_process_activated(self, _row, pid: int) -> None:
        from savesmith.views.trainer_editor import TrainerEditorPage

        page = TrainerEditorPage(
            window=self._window,
            definition=self._definition,
            pid=pid,
        )
        self._window.nav_view.push(page)
