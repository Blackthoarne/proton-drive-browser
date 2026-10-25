# Proton Drive Browser

A Nautilus-style window for Proton Drive on Omarchy. Every Drive action runs the
official Proton Drive CLI (`proton-drive`, 0.9.0); the app never calls the Proton API itself.

## Files

| File | Purpose |
|---|---|
| `drive-browser` | The app (Python, GTK4, libadwaita) |
| `protondrive_cli.py` | The only code that runs the CLI |
| `drive-browser.desktop` | App-launcher entry |
| `dev/fake-proton-drive` | Test stand-in for the CLI, works on a local folder |
| `dev/test_app.py` | End-to-end test against the fake (27 checks) |

## Dependencies

All are already installed on this machine: `python`, `python-gobject`, `gtk4`, `libadwaita`.
On a fresh Arch install: `sudo pacman -S python-gobject gtk4 libadwaita`.

The CLI goes in `~/.local/bin/proton-drive` (from proton.me/download/drive/cli, check the SHA-512).
Sign in once with `proton-drive auth login`. The session stays in the GNOME keyring.

## Run

```
~/Projects/proton-drive-browser/drive-browser
```

To add it to the app launcher (Super+Space):

```
cp ~/Projects/proton-drive-browser/drive-browser.desktop ~/.local/share/applications/
```

## Test

```
python3 -I ~/Projects/proton-drive-browser/dev/test_app.py
```

The test stops at once if it would use the real CLI.

## Behaviour choices

- Upload of a file that already exists: adds a new version (Proton keeps the old one).
- Download of a file that already exists locally: saves a renamed copy, never overwrites.
- Folders merge in both directions.
- Delete moves to Proton Trash after a confirmation. In Trash, Delete removes permanently after a second confirmation.
- Open (double-click a file) downloads a copy to `~/.cache/drive-browser/open` and opens it. Edits to that copy are not uploaded.

## CLI limits that shaped the design

- No progress output in JSON mode, so transfers show a spinner, not a percentage. Each can be cancelled.
- Listing a folder gives no item count, so the Size column shows "—" for folders.
- Search uses the current folder only (the CLI's search is experimental).
- Trashed items are found by name only, so two trashed items with the same name are ambiguous.
- The CLI cannot open folders inside Trash or list Devices in detail.
- No starring, recent files or thumbnails in the list.
- No sync and no mount: this is a browser, not a sync client.

## License

MIT. See `LICENSE`.
