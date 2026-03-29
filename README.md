# SaveSmith

A modular save game editor for Linux, built with GTK4 and libadwaita.

SaveSmith is a pure engine — all game-specific knowledge lives in downloadable definition files and plugins, so new games can be supported without updating the application.

## How it works

1. **Game definitions** describe save file formats, editable fields, and required plugins
2. **Plugins** handle format-specific operations (compression, encryption, binary parsing)
3. **Definitions and plugins** are downloaded on demand from this repository and verified with Ed25519 signatures before loading

## Supported games

| Game | Fields |
|------|--------|
| Big Ambitions | Money, Energy, Hunger, Happiness, Vehicle Damage/Fuel toggles |

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
  core/           # Engine: definitions, plugins, save I/O, signing
  views/          # GTK4/libadwaita UI
content/
  definitions/    # Game definition JSON files
  plugins/        # Format and search plugins
  manifest.json   # Signed content manifest
tools/            # Developer utilities (key generation, manifest signing)
```

### Plugin types

- **Format plugins** — handle compression/encryption layers (gzip, zip, etc.)
- **Search plugins** — find and read/write values in binary save data (UTF-16LE .NET serialization, JSON, XML, etc.)

### Security

All downloadable content is verified before execution:

- Content manifest is signed with Ed25519
- Each file is checked against SHA256 hashes in the manifest
- Plugins are re-verified on every launch
- Downloads restricted to this repository only

## License

GPL-3.0-or-later

---

## AI assistance

This application was developed with the help of [Claude](https://claude.ai) by Anthropic. Claude assisted with architecture decisions, implementation, and debugging throughout the project.
