import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from engine.syncthing import SYNCTHING_API_KEY_ENV, SYNCTHING_URL_ENV, get_folder_status, summarize_status


class _StubHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.requests.append((self.path, self.headers.get("X-API-Key")))
        if self.server.status_code != 200:
            self.send_response(self.server.status_code)
            self.end_headers()
            return
        body = json.dumps(self.server.payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


@pytest.fixture
def stub_syncthing():
    server = HTTPServer(("127.0.0.1", 0), _StubHandler)
    server.requests = []
    server.payload = {"state": "idle"}
    server.status_code = 200
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_get_folder_status_returns_none_without_api_key(monkeypatch):
    monkeypatch.delenv(SYNCTHING_API_KEY_ENV, raising=False)
    assert get_folder_status("some-folder") is None


def test_get_folder_status_queries_real_endpoint_with_api_key(monkeypatch, stub_syncthing):
    monkeypatch.setenv(SYNCTHING_API_KEY_ENV, "test-key-123")
    monkeypatch.setenv(SYNCTHING_URL_ENV, f"http://127.0.0.1:{stub_syncthing.server_port}")
    stub_syncthing.payload = {"state": "syncing", "needFiles": 3}

    result = get_folder_status("hotdata-folder")

    assert result == {"state": "syncing", "needFiles": 3}
    path, api_key = stub_syncthing.requests[0]
    assert path == "/rest/db/status?folder=hotdata-folder"
    assert api_key == "test-key-123"


def test_get_folder_status_returns_none_on_unreachable_server(monkeypatch):
    monkeypatch.setenv(SYNCTHING_API_KEY_ENV, "test-key-123")
    monkeypatch.setenv(SYNCTHING_URL_ENV, "http://127.0.0.1:1")  # nothing listens here
    assert get_folder_status("some-folder") is None


def test_get_folder_status_returns_none_on_http_error(monkeypatch, stub_syncthing):
    monkeypatch.setenv(SYNCTHING_API_KEY_ENV, "test-key-123")
    monkeypatch.setenv(SYNCTHING_URL_ENV, f"http://127.0.0.1:{stub_syncthing.server_port}")
    stub_syncthing.status_code = 404
    assert get_folder_status("nonexistent-folder") is None


def test_summarize_status_idle():
    assert summarize_status({"state": "idle"}) == "syncthing: idle"


def test_summarize_status_syncing_with_remaining_files():
    assert summarize_status({"state": "syncing", "needFiles": 5}) == "syncthing: syncing (5 file(s) remaining)"


def test_summarize_status_syncing_with_zero_need_files_shown_plain():
    # needFiles can be 0 for an instant between "syncing" and "idle" - don't
    # claim files are remaining when the count says there are none.
    assert summarize_status({"state": "syncing", "needFiles": 0}) == "syncthing: syncing"


def test_summarize_status_unknown_state_key_missing():
    assert summarize_status({}) == "syncthing: unknown"
