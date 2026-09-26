import json
import os
import urllib.error
import urllib.request
from typing import Optional

from engine.logger import get_logger

logger = get_logger()

SYNCTHING_URL_ENV = "SYNC_MANAGER_SYNCTHING_URL"
SYNCTHING_API_KEY_ENV = "SYNC_MANAGER_SYNCTHING_API_KEY"
DEFAULT_SYNCTHING_URL = "http://127.0.0.1:8384"


def get_folder_status(folder_id: str) -> Optional[dict]:
    """Queries Syncthing's local REST API (GET /rest/db/status) for one folder's
    real sync state - this app only supervises/watches Hot Data folders itself
    (see CLAUDE.md's Hot Data decision), so "is it actually synced" has to come
    from Syncthing, not be guessed from local file events. Returns None (never
    raises) if SYNC_MANAGER_SYNCTHING_API_KEY isn't set, Syncthing isn't
    reachable, or the folder_id doesn't exist there - callers must treat that as
    "status unknown", not an error, the same tolerance engine/alerting.py has
    for an unset/unreachable webhook."""
    api_key = os.environ.get(SYNCTHING_API_KEY_ENV)
    if not api_key:
        return None

    base_url = os.environ.get(SYNCTHING_URL_ENV, DEFAULT_SYNCTHING_URL).rstrip("/")
    url = f"{base_url}/rest/db/status?folder={folder_id}"
    try:
        request = urllib.request.Request(url, headers={"X-API-Key": api_key})
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, OSError, ValueError) as exc:
        logger.warning("Could not query Syncthing status for folder %r: %s", folder_id, exc)
        return None


def summarize_status(status: dict) -> str:
    """Turns a raw /rest/db/status payload into one short line for the dashboard.
    Syncthing's own `state` values (idle/scanning/syncing/error/...) are shown
    as-is rather than remapped, since they're already the vocabulary a user
    checking Syncthing's own UI would recognize."""
    state = status.get("state", "unknown")
    need_files = status.get("needFiles", 0)
    if state == "syncing" and need_files:
        return f"syncthing: {state} ({need_files} file(s) remaining)"
    return f"syncthing: {state}"
