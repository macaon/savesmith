# SaveSmith

A modular save game editor and trainer for Linux, built with GTK4 and libadwaita.

SaveSmith is a pure engine — all game-specific knowledge lives in downloadable definition files and plugins, so new games can be supported without updating the application.

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
| FTL: Faster Than Light | Trainer | Infinite fuel/scrap/missiles/drone parts, infinite power, invincible hull, infinite cloaking |
| Balatro | Trainer | Infinite money |

More games can be added by creating definition files — contributions welcome.

## Building

### Flatpak (recommended)

```bash
cd flatpak
flatpak-builder --force-clean --user --install builddir io.github.savesmith.json
flatpak run io.github.savesmith
```

### From source

Requires Python 3.11+, GTK4, libadwaita, and the `cryptography` package.

```bash
python -m savesmith.main
```

## Architecture

```
savesmith/
  core/           # Engine: definitions, plugins, save I/O, signing, trainer
  views/          # GTK4/libadwaita UI
content/
  definitions/    # Game definition JSON files
  plugins/        # Format, search, and memory plugins
  manifest.json   # Signed content manifest
tools/            # Developer utilities (key generation, manifest signing)
```

## Plugins

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

### Security

All downloadable content is verified before execution:

- Content manifest is signed with Ed25519
- Each file is checked against SHA256 hashes in the manifest
- Plugins are re-verified on every launch
- Downloads restricted to this repository only

## License

GPL-3.0-or-later

---

## AI Assistance

This application was developed with the help of [Claude](https://claude.ai) by Anthropic. Claude assisted with architecture decisions, implementation, and debugging throughout the project.
