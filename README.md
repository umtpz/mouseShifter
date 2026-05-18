# MouseShifter

Per-device mouse sensitivity switcher for Windows. Automatically applies the correct sensitivity and acceleration settings whenever a specific mouse becomes active.

## The Problem

When using multiple mice — a gaming mouse at your desk, a couch remote with a trackpad, a precision mouse for creative work — Windows applies a single global sensitivity setting to all of them. Switching between devices means constantly digging into Settings to readjust.

MouseShifter detects which mouse is moving and instantly applies that device's saved settings.

## Use Case

| Device | Setup | Config |
|---|---|---|
| Logitech G502X Plus | 4K TV, 25K DPI, 100% scale | Speed: 3, Accel: Off |
| Logitech K400+ | Living room TV, touchpad | Speed: 18, Accel: On |
| Logitech Master 3 | Desktop, productivity | Speed: 10, Accel: Off |

## Installation

**Requirements:** Windows 10/11, Python 3.10+

```bash
pip install pywin32 customtkinter pillow pystray
python main.py
```

**Or build a standalone executable:**

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --icon=icon.ico --name=MouseShifter main.py
```

The executable will be at `dist\MouseShifter.exe`.

## How It Works

- Uses the **Windows Raw Input API** to listen for mouse movement events at the hardware level, identifying each physical device by its handle
- When a mouse moves, its handle is pushed to a queue — the UI thread drains this queue every 16ms (≈60fps) and applies settings only when the active device changes
- Settings are written via `SystemParametersInfo` (the same API Windows Settings uses)
- Device data is persisted to `devices.json` alongside the executable

## Features

- **Auto-detection** — plug in a mouse and move it; it appears instantly as a card
- **Per-device settings** — sensitivity (1–20) and pointer acceleration saved independently
- **Persistent** — names, sensitivity and acceleration values survive restarts; known devices are shown immediately on launch
- **System tray** — runs in the background; double-click the tray icon to open, minimize to hide, × to quit
- **Run at Startup** — toggle in the footer; works with both `.py` and PyInstaller `.exe`
- **Remove device** — trash icon on each card removes the device; it will be re-detected on next movement

## Interface

```
┌──────────────────────────────────────┐   ┌──────────────────────────────────────┐
│  VID: 046D   PID: C547            ●  │   │  VID: 046D   PID: C52B            ●  │
│  ┌──────────────────────────────┐    │   │  ┌──────────────────────────────┐    │
│  │ Logitech G502X Plus          │    │   │  │ Logitech K400+               │    │
│  └──────────────────────────────┘    │   │  └──────────────────────────────┘    │
│ ──────────────────────────────────── │   │ ──────────────────────────────────── │
│  SENSITIVITY                 3 / 20  │   │  SENSITIVITY                18 / 20  │
│  ●────────────────────────────────   │   │  ●────────────────────────────────   │
│  Default: 3                          │   │  Default: 3                          │
│ ──────────────────────────────────── │   │ ──────────────────────────────────── │
│  ACCELERATION       Off  ◯          │   │  ACCELERATION       Off  ◯          │
│  Default: Off                        │   │  Default: Off                        │
│                                   🗑  │   │                                   🗑  │
└──────────────────────────────────────┘   └──────────────────────────────────────┘
☑ Run at Startup        System Speed: 3/20   Accel: Off    ● Active → Logitech G502X Plus
```

## Technical Notes

- Raw Input thread only writes to a bounded queue (`maxsize=256`) — no Windows API calls, no UI interaction
- All `SystemParametersInfo` calls happen on the main thread, eliminating freeze issues from concurrent API access
- Sensitivity slider uses 150ms debounce to avoid hammering the Windows API while dragging
- On first detection, the device snapshots the current Windows speed and acceleration as its default values

## Files

| File | Description |
|---|---|
| `main.py` | Application source |
| `devices.json` | Saved device profiles (auto-created) |
| `icon.ico` | Application icon (auto-created on first run) |