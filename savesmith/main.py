"""GApplication entry point for SaveSmith."""

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(name)s %(levelname)s: %(message)s",
)
log = logging.getLogger(__name__)

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk

from savesmith import __version__


class SaveSmithApplication(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="io.github.savesmith",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )

    def do_activate(self):
        from savesmith.window import SaveSmithWindow

        if not self.props.active_window:
            # Actions
            quit_action = Gio.SimpleAction.new("quit", None)
            quit_action.connect("activate", self._on_quit)
            self.add_action(quit_action)

            about_action = Gio.SimpleAction.new("about", None)
            about_action.connect("activate", self._on_about)
            self.add_action(about_action)

            shortcuts_action = Gio.SimpleAction.new("shortcuts", None)
            shortcuts_action.connect("activate", self._on_shortcuts)
            self.add_action(shortcuts_action)

            # Keyboard shortcuts
            self.set_accels_for_action("app.quit", ["<Control>q"])
            self.set_accels_for_action("app.shortcuts", ["<Control>question"])
            self.set_accels_for_action("window.close", ["<Control>w"])

            win = SaveSmithWindow(application=self)
            win.present()
        else:
            self.props.active_window.present()

    def _on_quit(self, _action, _param):
        win = self.props.active_window
        if win:
            win.close()
        else:
            self.quit()

    def _on_about(self, _action, _param):
        about = Adw.AboutDialog(
            application_name="SaveSmith",
            application_icon="io.github.savesmith",
            developer_name="macaon",
            version=__version__,
            website="https://github.com/macaon/savesmith",
            issue_url="https://github.com/macaon/savesmith/issues",
            license_type=Gtk.License.GPL_3_0,
            comments="A modular save game editor and trainer for Linux.",
        )
        about.present(self.props.active_window)

    def _on_shortcuts(self, _action, _param):
        builder = Gtk.Builder.new_from_string(
            """
            <interface>
              <object class="GtkShortcutsWindow" id="shortcuts">
                <property name="modal">true</property>
                <child>
                  <object class="GtkShortcutsSection">
                    <child>
                      <object class="GtkShortcutsGroup">
                        <property name="title">General</property>
                        <child>
                          <object class="GtkShortcutsShortcut">
                            <property name="accelerator">&lt;Control&gt;q</property>
                            <property name="title">Quit</property>
                          </object>
                        </child>
                        <child>
                          <object class="GtkShortcutsShortcut">
                            <property name="accelerator">&lt;Control&gt;w</property>
                            <property name="title">Close Window</property>
                          </object>
                        </child>
                        <child>
                          <object class="GtkShortcutsShortcut">
                            <property name="accelerator">&lt;Ctrl&gt;question</property>
                            <property name="title">Keyboard Shortcuts</property>
                          </object>
                        </child>
                      </object>
                    </child>
                  </object>
                </child>
              </object>
            </interface>
            """,
            -1,
        )
        win = builder.get_object("shortcuts")
        win.set_transient_for(self.props.active_window)
        win.present()


def main():
    app = SaveSmithApplication()
    try:
        sys.exit(app.run(sys.argv))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
