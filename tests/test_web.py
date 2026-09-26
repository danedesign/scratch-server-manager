import pytest

from main import Manager
from tests.conftest import make_sqlite_db
from web.app import create_app


@pytest.fixture
def client(tmp_path):
    cfg_path = tmp_path / "folders.yaml"
    cfg_path.write_text("folders: []\n")
    manager = Manager(cfg_path)
    manager.reload()
    app = create_app(manager)
    app.config["TESTING"] = True
    try:
        with app.test_client() as c:
            c.manager = manager
            c.cfg_path = cfg_path
            yield c
    finally:
        manager.stop_all()


def test_status_page_empty(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"No folders configured" in resp.data


def test_status_page_lists_configured_folder(client, tmp_path):
    watched = tmp_path / "hotfolder"
    watched.mkdir()
    client.cfg_path.write_text(f"folders:\n- path: {watched.as_posix()}\n  profile: hot_data\n")
    client.manager.reload()

    resp = client.get("/")
    assert str(watched).encode() in resp.data
    assert b"hot_data" in resp.data


def test_add_form_prefills_from_query_args(client):
    resp = client.get("/add?path=%2Fsrv%2Ffoo&versions_to_keep=7")
    assert b"/srv/foo" in resp.data
    assert b'value="7"' in resp.data


def test_add_hot_data_success(client, tmp_path):
    watched = tmp_path / "hotfolder"
    watched.mkdir()
    resp = client.post("/add/hot_data", data={"path": str(watched), "versions_to_keep": "5"})
    assert resp.status_code == 302
    raw = client.cfg_path.read_text()
    assert "hot_data" in raw and str(watched.as_posix()) in raw.replace("\\", "/")


def test_add_hot_data_rejects_missing_path(client):
    resp = client.post("/add/hot_data", data={"versions_to_keep": "5"}, follow_redirects=True)
    assert b"required" in resp.data.lower()


def test_add_hot_data_rejects_nonexistent_path(client, tmp_path):
    resp = client.post(
        "/add/hot_data",
        data={"path": str(tmp_path / "nope"), "versions_to_keep": "5"},
        follow_redirects=True,
    )
    assert b"not an existing directory" in resp.data


def test_add_hot_data_rejects_non_integer_versions(client, tmp_path):
    watched = tmp_path / "hotfolder"
    watched.mkdir()
    resp = client.post(
        "/add/hot_data", data={"path": str(watched), "versions_to_keep": "not-a-number"}, follow_redirects=True
    )
    assert b"positive integer" in resp.data


def test_add_wechat_vault_success(client, tmp_path):
    staging = tmp_path / "staging"
    vault = tmp_path / "vault"
    staging.mkdir()
    resp = client.post(
        "/add/wechat_vault",
        data={
            "staging_path": str(staging),
            "vault_path": str(vault),
            "promote_interval_minutes": "45",
            "keep_failed_staging": "on",
        },
    )
    assert resp.status_code == 302
    raw = client.cfg_path.read_text()
    assert "wechat_vault" in raw and "45" in raw


def test_add_wechat_vault_rejects_same_staging_and_vault(client, tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    resp = client.post(
        "/add/wechat_vault",
        data={"staging_path": str(staging), "vault_path": str(staging), "promote_interval_minutes": "60"},
        follow_redirects=True,
    )
    assert b"must be different" in resp.data


def test_browse_lists_subdirectories(client, tmp_path):
    (tmp_path / "alpha").mkdir()
    (tmp_path / "beta").mkdir()
    resp = client.get(f"/browse?path={tmp_path}&target=path")
    assert b"alpha" in resp.data and b"beta" in resp.data


def test_browse_nonexistent_path_falls_back_to_home(client):
    resp = client.get("/browse?path=C:%5Cnope%5Cnope&target=path")
    assert resp.status_code == 200
    assert b"not a directory" in resp.data


def test_hot_data_pause_resume_via_routes(client, tmp_path):
    # The routes only write folders.yaml - in the real running app, main.py's
    # config FolderWatcher is what notices the change and calls reload()
    # asynchronously (see CLAUDE.md's "known, accepted timing quirk"). That
    # watcher isn't running in this test, so reload() is called explicitly
    # here to stand in for it.
    watched = tmp_path / "hotfolder"
    watched.mkdir()
    client.cfg_path.write_text(f"folders:\n- path: {watched.as_posix()}\n  profile: hot_data\n")
    client.manager.reload()

    client.post("/folders/hot_data/pause", data={"path": str(watched)})
    client.manager.reload()
    assert client.manager.status()[0].status == "paused"

    client.post("/folders/hot_data/resume", data={"path": str(watched)})
    client.manager.reload()
    assert client.manager.status()[0].status == "ok"


def test_wechat_vault_pause_promote_resume_via_routes(client, tmp_path):
    staging = tmp_path / "staging"
    vault = tmp_path / "vault"
    staging.mkdir()
    make_sqlite_db(staging / "MSG0.db")
    client.cfg_path.write_text(
        f"folders:\n- profile: wechat_vault\n  staging_path: {staging.as_posix()}\n"
        f"  vault_path: {vault.as_posix()}\n  promote_interval_minutes: 60\n"
    )
    client.manager.reload()

    client.post("/folders/wechat_vault/pause", data={"staging_path": str(staging)})
    client.manager.reload()
    assert client.manager.status()[0].status == "paused"

    # promote_wechat_vault doesn't touch folders.yaml, so it needs no reload -
    # it calls promote_now() directly on the already-loaded profile.
    client.post("/folders/wechat_vault/promote", data={"staging_path": str(staging)})
    row = client.manager.status()[0]
    assert row.status == "paused"
    assert "last manual promote: ok" in row.reason

    client.post("/folders/wechat_vault/resume", data={"staging_path": str(staging)})
    client.manager.reload()
    assert client.manager.status()[0].status in ("ok", "unknown")
    assert client.manager._scheduler.next_run(str(staging)) is not None
