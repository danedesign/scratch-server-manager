"""Sync Manager Launcher - a tiny native window (WebView2-based via pywebview,
no Chromium bundling) that finds whichever machine on the tailnet is running
Sync Manager and opens its dashboard, so the user never has to remember or
type an IP/URL themselves.

Discovery: shells out to the Tailscale CLI (`tailscale status --json`, already
installed as part of Tailscale itself) to list every device on the tailnet,
then probes each one's :8420/static/manifest.json concurrently, looking for
the one whose manifest identifies it as "Sync Manager". The found IP is
cached locally so future launches skip the network scan entirely unless the
cached address stops responding.
"""

import ipaddress
import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from shutil import which

import requests
import webview

APP_NAME = "Sync Manager"
DASHBOARD_PORT = 8420
PROBE_TIMEOUT = 1.5
TAILSCALE_STATUS_TIMEOUT = 5
CONFIG_PATH = Path.home() / ".sync_manager_launcher.json"

# Windows-only: suppresses the console window that would otherwise flash
# briefly when subprocess launches tailscale.exe from a windowed (no-console)
# PyInstaller build.
_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

LOADING_HTML = """
<!doctype html><html><head><meta charset="utf-8"><title>Sync Manager</title>
<style>
  body { font-family: system-ui, sans-serif; background: #111; color: #eee;
         display: flex; align-items: center; justify-content: center;
         height: 100vh; margin: 0; }
  .box { text-align: center; }
  .spinner { width: 40px; height: 40px; border: 3px solid #333;
             border-top-color: #2f6fbf; border-radius: 50%;
             animation: spin 0.8s linear infinite; margin: 0 auto 1rem; }
  @keyframes spin { to { transform: rotate(360deg); } }
  p { color: #888; }
</style></head>
<body><div class="box"><div class="spinner"></div>
<p>Finding Sync Manager on your tailnet&hellip;</p></div></body></html>
"""

def error_html(detail: str) -> str:
    return f"""
<!doctype html><html><head><meta charset="utf-8"><title>Sync Manager</title>
<style>
  body {{ font-family: system-ui, sans-serif; background: #111; color: #eee;
          display: flex; align-items: center; justify-content: center;
          height: 100vh; margin: 0; }}
  .box {{ text-align: center; max-width: 420px; }}
  p {{ color: #888; }}
  button {{ margin-top: 1rem; padding: 0.5rem 1.25rem; background: #2f6fbf;
            color: #fff; border: none; border-radius: 4px; cursor: pointer;
            font-size: 0.95rem; }}
</style></head>
<body><div class="box">
<h2>Couldn't find Sync Manager</h2>
<p>{detail}</p>
<p>Make sure Tailscale is running and the Sync Manager service is up.</p>
<button onclick="pywebview.api.retry()">Retry</button>
</div></body></html>
"""


def _find_tailscale_exe() -> str | None:
    found = which("tailscale")
    if found:
        return found
    default = Path("C:/Program Files/Tailscale/tailscale.exe")
    if default.exists():
        return str(default)
    return None


def _candidate_ips() -> list[str]:
    """Every online tailnet device's IPv4 Tailscale address (self included)."""
    exe = _find_tailscale_exe()
    if exe is None:
        return []
    try:
        proc = subprocess.run(
            [exe, "status", "--json"],
            capture_output=True, text=True, timeout=TAILSCALE_STATUS_TIMEOUT,
            creationflags=_SUBPROCESS_FLAGS,
        )
        data = json.loads(proc.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return []

    nodes = [data.get("Self") or {}] + list((data.get("Peer") or {}).values())
    ips = []
    for node in nodes:
        if not node.get("Online", True):
            continue
        for raw_ip in node.get("TailscaleIPs", []):
            try:
                addr = ipaddress.ip_address(raw_ip)
            except ValueError:
                continue
            if addr.version == 4:
                ips.append(str(addr))
                break
    return ips


def _probe(ip: str) -> str | None:
    """Returns `ip` if it's actually running Sync Manager, else None."""
    try:
        resp = requests.get(f"http://{ip}:{DASHBOARD_PORT}/static/manifest.json", timeout=PROBE_TIMEOUT)
        if resp.ok and resp.json().get("name") == APP_NAME:
            return ip
    except (requests.RequestException, ValueError):
        pass
    return None


def _load_cached_ip() -> str | None:
    try:
        return json.loads(CONFIG_PATH.read_text()).get("ip")
    except (OSError, json.JSONDecodeError):
        return None


def _save_cached_ip(ip: str) -> None:
    try:
        CONFIG_PATH.write_text(json.dumps({"ip": ip, "found_at": time.time()}))
    except OSError:
        pass  # non-fatal - just means next launch re-scans


def discover() -> str | None:
    """Cached IP first (fast path, most launches), falling back to a full
    tailnet scan if it's stale or nothing's cached yet."""
    cached = _load_cached_ip()
    if cached and _probe(cached):
        return cached

    candidates = _candidate_ips()
    if not candidates:
        return None
    with ThreadPoolExecutor(max_workers=min(16, len(candidates))) as pool:
        futures = [pool.submit(_probe, ip) for ip in candidates]
        for future in as_completed(futures):
            result = future.result()
            if result:
                _save_cached_ip(result)
                return result
    return None


class Api:
    def retry(self):
        threading.Thread(target=_run_discovery_and_navigate, daemon=True).start()


def _run_discovery_and_navigate():
    ip = discover()
    if ip:
        window.load_url(f"http://{ip}:{DASHBOARD_PORT}/")
    else:
        window.load_html(error_html("No tailnet device responded as Sync Manager."))


if __name__ == "__main__":
    api = Api()
    window = webview.create_window(APP_NAME, html=LOADING_HTML, width=1100, height=800, js_api=api)
    threading.Thread(target=_run_discovery_and_navigate, daemon=True).start()
    webview.start()
