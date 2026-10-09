"""AKPL: upload captured Aula F87 Pro profiles on Windows or macOS."""
from __future__ import annotations

import argparse
import ctypes
import json
import platform
import statistics
import sys
import time
from pathlib import Path

import hid

APP_DIR = Path(__file__).resolve().parent
PROFILE_DIR = APP_DIR / "profiles"
PROFILES = {
    "windows": PROFILE_DIR / "windows.json",
    "macos": PROFILE_DIR / "macos.json",
}

VID = 0x3554
PID = 0xFA09
PREFERRED_USAGE_PAGES = (0xFF02, 0xFF04)
REPORT_ID = 0x13
REPORT_SIZE = 20
EXPECTED_REPORTS = 159
IS_WINDOWS = platform.system() == "Windows"

if IS_WINDOWS:
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
    _hiddll = ctypes.WinDLL("hid.dll", use_last_error=True)
    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _hiddll.HidD_SetOutputReport.restype = wintypes.BOOLEAN
    _hiddll.HidD_SetOutputReport.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.ULONG,
    ]

    _GENERIC_READ = 0x80000000
    _GENERIC_WRITE = 0x40000000
    _FILE_SHARE_READ = 0x00000001
    _FILE_SHARE_WRITE = 0x00000002
    _OPEN_EXISTING = 3
    _INVALID_HANDLE = wintypes.HANDLE(-1).value


def _devices() -> list[dict]:
    return [
        device for device in hid.enumerate()
        if device["vendor_id"] == VID and device["product_id"] == PID
    ]


def _choose_path(usage_page: int | None = None) -> bytes:
    devices = _devices()
    if usage_page is not None:
        for device in devices:
            if device.get("usage_page") == usage_page:
                return device["path"]
        raise RuntimeError(f"No Aula HID collection found for usage page 0x{usage_page:04X}")

    for preferred in PREFERRED_USAGE_PAGES:
        for device in devices:
            if device.get("usage_page") == preferred:
                return device["path"]
    raise RuntimeError(f"Aula receiver VID={VID:04X} PID={PID:04X} was not found")


def _read_profile(name: str) -> tuple[list[bytes], list[float]]:
    path = PROFILES[name]
    if not path.is_file():
        raise RuntimeError(f"Profile file not found: {path}")
    with path.open("r", encoding="utf-8") as stream:
        records = json.load(stream)
    if not isinstance(records, list) or len(records) != EXPECTED_REPORTS:
        raise RuntimeError(f"{path.name} must contain exactly {EXPECTED_REPORTS} reports")

    reports: list[bytes] = []
    timestamps: list[float] = []
    for index, record in enumerate(records):
        try:
            report = bytes.fromhex(record["data"])
            timestamp = float(record["timestamp"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"Malformed report record {index} in {path.name}") from exc

        if len(report) != REPORT_SIZE:
            raise RuntimeError(f"Report {index} has {len(report)} bytes, expected {REPORT_SIZE}")
        if report[0] != REPORT_ID:
            raise RuntimeError(f"Report {index} has unexpected ID 0x{report[0]:02X}")
        if (sum(report[:19]) & 0xFF) != report[19]:
            raise RuntimeError(f"Report {index} has an invalid checksum")
        reports.append(report)
        timestamps.append(timestamp)

    if any(b < a for a, b in zip(timestamps, timestamps[1:])):
        raise RuntimeError(f"Timestamps in {path.name} are not ordered")
    return reports, timestamps


def _describe(name: str, reports: list[bytes], timestamps: list[float]) -> None:
    gaps = [b - a for a, b in zip(timestamps, timestamps[1:])]
    duration = timestamps[-1] - timestamps[0] if len(timestamps) > 1 else 0.0
    median_ms = statistics.median(gaps) * 1000 if gaps else 0.0
    print(f"Profile: {name} ({PROFILES[name].name})")
    print(f"Reports: {len(reports)}; captured duration: {duration:.2f}s; "
          f"median interval: {median_ms:.1f}ms")
    print(f"Report ID/checksum validation: OK")
    print(f"First report: {reports[0].hex(' ')}")


class AulaDevice:
    """Open the Aula vendor HID collection and send output reports."""

    def __init__(self, usage_page: int | None = None):
        self.path = _choose_path(usage_page)
        self.device = None
        self.handle = None

    def open(self) -> None:
        if IS_WINDOWS:
            handle = _kernel32.CreateFileW(
                self.path.decode("utf-8", errors="replace"),
                _GENERIC_READ | _GENERIC_WRITE,
                _FILE_SHARE_READ | _FILE_SHARE_WRITE,
                None,
                _OPEN_EXISTING,
                0,
                None,
            )
            if handle == _INVALID_HANDLE:
                raise OSError(f"CreateFileW failed (Windows error {ctypes.get_last_error()})")
            self.handle = handle
        else:
            self.device = hid.device()
            self.device.open_path(self.path)

    def write(self, report: bytes) -> None:
        if IS_WINDOWS:
            if self.handle is None:
                raise RuntimeError("HID device is not open")
            buffer = ctypes.create_string_buffer(report, len(report))
            if not _hiddll.HidD_SetOutputReport(self.handle, buffer, len(report)):
                raise OSError(f"HidD_SetOutputReport failed (Windows error {ctypes.get_last_error()})")
            return

        if self.device is None:
            raise RuntimeError("HID device is not open")
        written = self.device.write(report)
        if written != len(report):
            raise OSError(f"hidapi wrote {written} of {len(report)} report bytes")

    def close(self) -> None:
        if self.handle is not None:
            _kernel32.CloseHandle(self.handle)
            self.handle = None
        if self.device is not None:
            self.device.close()
            self.device = None


def _print_devices() -> None:
    devices = _devices()
    if not devices:
        print(f"No Aula receiver found (VID={VID:04X}, PID={PID:04X})")
        return
    print(f"Aula receiver (VID={VID:04X}, PID={PID:04X}) HID collections:")
    for device in devices:
        print("  interface={interface_number} usage_page=0x{usage_page:04X} "
              "usage=0x{usage:04X}".format(**device))


def _upload(name: str, usage_page: int | None = None) -> None:
    reports, timestamps = _read_profile(name)
    _describe(name, reports, timestamps)
    device = AulaDevice(usage_page)
    device.open()
    try:
        print("Uploading with the original Aula report timing...")
        for index, report in enumerate(reports):
            device.write(report)
            if index + 1 < len(reports):
                time.sleep(max(0.0, timestamps[index + 1] - timestamps[index]))
            if (index + 1) % 50 == 0:
                print(f"  sent {index + 1}/{len(reports)} reports")
    finally:
        device.close()
    print(f"Profile '{name}' uploaded.")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="akpl",
        description="Upload the captured Aula F87 Pro Windows or MacOS profile.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("profiles", help="list the two included profiles")
    commands.add_parser("devices", help="list matching Aula HID collections")
    commands.add_parser("probe", help="open and close the HID collection without writing")

    dry_run = commands.add_parser("dry-run", help="validate a profile without uploading")
    dry_run.add_argument("profile", choices=PROFILES)

    upload = commands.add_parser("upload", help="upload a profile to the keyboard")
    upload.add_argument("profile", choices=PROFILES)
    upload.add_argument("--usage-page", type=lambda value: int(value, 0), default=None,
                        help="select a HID usage page, e.g. 0xFF02")
    args = parser.parse_args()

    try:
        if args.command == "profiles":
            print("windows  Windows recovery profile")
            print("macos    MacOS profile: FN=Option, RAlt=Command, Super/Menu=FN")
            return 0
        if args.command == "devices":
            _print_devices()
            return 0
        if args.command == "probe":
            device = AulaDevice()
            device.open()
            device.close()
            print("HID collection opened and closed; no reports were sent.")
            return 0

        reports, timestamps = _read_profile(args.profile)
        _describe(args.profile, reports, timestamps)
        if args.command == "dry-run":
            print("Dry run only; the keyboard was not changed.")
            print(f"To upload: python akpl.py upload {args.profile}")
            return 0
        _upload(args.profile, args.usage_page)
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"AKPL error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nUpload interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
