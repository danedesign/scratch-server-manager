# Sync Manager Launcher

A tiny native window (WebView2 via `pywebview` — no Chromium bundling, no
Electron) that finds whichever machine on your tailnet is running Sync
Manager and opens its dashboard directly. No URL to remember or type.

## How discovery works

1. Runs `tailscale status --json` (the Tailscale CLI, already installed
   alongside Tailscale itself) to list every device on the tailnet.
2. Probes each device's `:8420/static/manifest.json` concurrently, looking
   for the one whose manifest identifies it as `"Sync Manager"`.
3. Caches the found IP (`~/.sync_manager_launcher.json`) so future launches
   skip straight to it — falls back to a full re-scan automatically if the
   cached address ever stops responding.
4. Navigates the window to that dashboard.

Chosen over Tauri/Electron because it needs no new toolchain: everything
(`pywebview`, `requests`, `pyinstaller`) is pip-installable, and Windows
already ships WebView2. A Tauri build would additionally need the MSVC C++
Build Tools installed.

## Run it directly (no packaging)

```bash
cd desktop-app
python -m venv .venv
.venv\Scripts\activate      # Windows; `source .venv/bin/activate` elsewhere
pip install -r requirements.txt
python launcher.py
```

## Build a standalone .exe

```bash
cd desktop-app
.venv\Scripts\activate
pyinstaller --onefile --windowed --name "SyncManager" --icon icon.ico launcher.py
```

Output lands in `dist/SyncManager.exe` — a single file, no installer needed,
copy it anywhere (Desktop, Start Menu shortcut, etc.).

## Notes

- Windows-only as built (`_SUBPROCESS_FLAGS` in `launcher.py` suppresses a
  console flash specific to Windows) — `pywebview` itself is cross-platform,
  so this would need only that one flag made conditional to run on macOS/Linux
  too, not a rewrite.
- Matches the running Sync Manager instance by its PWA manifest's `name`
  field (`"Sync Manager"`) — see `web/static/manifest.json` in the main repo.
  If that's ever renamed, update `APP_NAME` in `launcher.py` to match.
