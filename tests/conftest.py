import logging
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


def wait_until(predicate, timeout=5.0, interval=0.05):
    """Polls `predicate` until it's truthy or `timeout` elapses, for tests that
    depend on an async filesystem watcher or scheduler thread. Returns the last
    (falsy) result on timeout rather than raising, so callers can assert with a
    clear failure message instead of a bare TimeoutError."""
    deadline = time.monotonic() + timeout
    result = predicate()
    while not result and time.monotonic() < deadline:
        time.sleep(interval)
        result = predicate()
    return result


class _CaptureHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.server.received.append(self.rfile.read(length).decode("utf-8"))
        self.send_response(200)
        self.end_headers()

    def log_message(self, fmt, *args):
        pass


@pytest.fixture
def capture_server():
    """A local HTTP server that records POST bodies, standing in for a real
    ntfy/webhook endpoint so alerting tests never touch a real external service."""
    server = HTTPServer(("127.0.0.1", 0), _CaptureHandler)
    server.received = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=2)


def make_sqlite_db(path, rows=10):
    """Writes a small valid SQLite database to `path`, overwriting anything there."""
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, body TEXT)")
    conn.executemany("INSERT INTO messages (body) VALUES (?)", [(f"msg{i}",) for i in range(rows)])
    conn.commit()
    conn.close()


@pytest.fixture
def sqlite_db_factory():
    return make_sqlite_db


class _ListHandler(logging.Handler):
    """engine/logger.py sets propagate=False on its logger (deliberately, to
    avoid duplicate output), which means pytest's caplog - which only listens
    on the root logger - can never see its records. Attach directly instead."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def messages(self):
        return [r.getMessage() for r in self.records]


@pytest.fixture
def app_log():
    """Captures records from the app's own "sync_manager" logger."""
    handler = _ListHandler()
    logger = logging.getLogger("sync_manager")
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
