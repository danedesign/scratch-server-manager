import os
import urllib.error
import urllib.request

from engine.logger import get_logger

logger = get_logger()

NTFY_URL_ENV = "SYNC_MANAGER_NTFY_URL"


def send_alert(message: str) -> None:
    """Posts `message` as the raw body to the URL in SYNC_MANAGER_NTFY_URL - the
    shape ntfy.sh (and many simple webhook receivers) expect for a plain-text push.
    A JSON-payload sink (Slack/Discord-style incoming webhooks) would need a
    different body and is a natural next pluggable option, not built here since
    nothing in this project currently needs it."""
    url = os.environ.get(NTFY_URL_ENV)
    if not url:
        logger.info("Alert (not sent, %s unset): %s", NTFY_URL_ENV, message)
        return
    try:
        request = urllib.request.Request(url, data=message.encode("utf-8"), method="POST")
        urllib.request.urlopen(request, timeout=10)
    except (urllib.error.URLError, OSError) as exc:
        logger.error("Failed to send alert to %s: %s", url, exc)
