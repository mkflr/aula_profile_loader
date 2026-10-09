# Aula Keyboard Profile Loader

AKPL is a small command-line tool for uploading two captured Aula F87 Pro
profiles without the Windows-only Aula application:

- `macos`: FN=Option, Right Alt=Command, Super/Menu=Fn
- `windows`: recovery/default profile

The included profiles are captured HID report sessions, verified byte-for-byte
against the corresponding Aula application uploads (159 reports each). AKPL
preserves the original per-report timing: about 24 ms median, about 4.1 seconds
for the complete upload.

## Requirements

Python 3.10+ and `hidapi`:

```sh
python -m pip install -r requirements.txt
```

## Usage

Run commands from this directory.

```sh
# List profiles
python akpl.py profiles

# List matching Aula USB HID collections
python akpl.py devices

# Open and close the selected HID collection without sending anything
python akpl.py probe

# Validate and preview a profile without uploading
python akpl.py dry-run macos

# Upload the MacOS profile
python akpl.py upload macos

# Restore the Windows profile if needed
python akpl.py upload windows
```

The receiver should be connected over USB (use a USB-C adapter on a Mac if
needed). Upload changes the keyboard configuration. Keep the Windows recovery
profile available.

## Platform support

- **Windows:** uses `HidD_SetOutputReport`; upload has been tested.
- **macOS:** uses hidapi's `IOHIDDeviceSetReport` output-report backend. The
  backend is implemented, but still needs verification on a physical Mac.

If device access fails on macOS, run `python3 akpl.py probe` first and share
the exact error. Do not use the experimental `.bcf` compiler as a workaround.

## Scope

This compact release only uploads the two included F87 Pro profiles. It does
not parse or compile arbitrary `.bcf` files. The previous experimental BCF
converter and sniffer were removed because their output was not fully validated
and could leave keys unmapped.

The profile JSON files contain device-specific key mappings and lighting
settings from the captured sessions. Review them before redistributing the
repository.

## License

MIT. See `LICENSE`.
