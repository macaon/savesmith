# SaveSmith

A modular save game editor and trainer for Linux, built with GTK4 and libadwaita.

SaveSmith is a pure engine — all game-specific knowledge lives in definition files and plugins, so new games can be supported without updating the application.

## Features

### Save Editing

Edit save file values through a clean UI. Definitions describe the file format, editable fields, and required plugins. SaveSmith handles loading, decompression, editing, and saving with automatic backups.

### Trainer Mode

Attach to a running game and modify values in real time. Trainers support:

- **Live memory reading** — poll game state and display current values
- **Value freezing** — continuously write a value to keep it locked
- **Code patching** — NOP or modify game instructions (e.g. disable damage, infinite power)
- **Lua injection** — execute Lua code inside LuaJIT/LÖVE games via GDB-driven shellcode

Trainers work both natively and inside the Flatpak sandbox via the `org.freedesktop.Flatpak` host portal.

## Supported Games

| Game | Mode | Cheats |
|------|------|--------|
| Big Ambitions | Save Editor | Money, Energy, Hunger, Happiness, economy settings, difficulty, toggles |
| FTL: Faster Than Light (v1.6.29) | Trainer | Infinite fuel/scrap/missiles/drone parts, infinite power, invincible hull, infinite cloaking |
| Balatro (v1.0.1o) | Trainer | Infinite money/hands/discards, large hand size |
| Dave the Diver (v1.0.5.1791) | Save Editor | Gold, Bei, Research Points |
| Dave the Diver (v1.0.5.1791) | Trainer | Infinite oxygen, invincible |

More games can be added by creating definition files and plugins — contributions welcome.

## Building

### Flatpak (recommended)

```bash
cd flatpak
flatpak-builder --force-clean --user --install builddir io.github.savesmith.json
flatpak run io.github.savesmith
```

### From source

Requires Python 3.11+, GTK4, and libadwaita.

```bash
python -m savesmith.main
```

## Architecture

```
savesmith/
  core/           # Engine: definitions, plugins, save I/O, trainer
  views/          # GTK4/libadwaita UI
content/
  definitions/    # Game definition JSON files
  plugins/        # Format, search, and memory plugins
tools/            # Developer utilities
```

## Plugins

Plugins are Python files dropped into the `plugins/` directory. Each plugin exposes a class with `id` and `type` attributes.

### Save Editor Plugins

| Plugin | Type | Description |
|--------|------|-------------|
| `format_gzip` | Format | Gzip compression/decompression for save files |
| `search_utf16le` | Search | Find and read/write values by UTF-16LE field name in .NET binary data |

### Trainer Plugins

| Plugin | Type | Description |
|--------|------|-------------|
| `memory_static` | Memory | Read/write values at a fixed offset from a module base address |
| `memory_pointer_chain` | Memory | Follow multi-level pointer chains with fallback paths for optional subsystems |
| `lua_inject` | Memory | Execute Lua code in LuaJIT/LÖVE games via GDB shellcode injection |
| `code_cave` | Memory | Install guarded patches via rwx trampolines for conditional code modification |

## License

GPL-3.0-or-later

---

## AI Assistance

This application was developed with the help of [Claude](https://claude.ai) by Anthropic. Claude assisted with architecture decisions, implementation, and debugging throughout the project.
