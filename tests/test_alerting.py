from engine.alerting import send_alert


def test_unconfigured_does_not_send(monkeypatch, capture_server):
    monkeypatch.delenv("SYNC_MANAGER_NTFY_URL", raising=False)
    send_alert("should not be sent")
    assert capture_server.received == []


def test_configured_sends_exact_message(monkeypatch, capture_server):
    monkeypatch.setenv("SYNC_MANAGER_NTFY_URL", f"http://127.0.0.1:{capture_server.server_address[1]}/")
    send_alert("hello from the test suite")
    assert capture_server.received == ["hello from the test suite"]


def test_unreachable_url_does_not_raise(monkeypatch):
    monkeypatch.setenv("SYNC_MANAGER_NTFY_URL", "http://127.0.0.1:1/")  # nothing listens here
    send_alert("this should fail quietly")  # must not raise
