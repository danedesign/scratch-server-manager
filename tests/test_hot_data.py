import time

import pytest

from profiles.hot_data import HotDataProfile
from tests.conftest import wait_until


@pytest.fixture
def running_profile(tmp_path):
    watched = tmp_path / "watched"
    versions = tmp_path / "watched.versions"
    watched.mkdir()
    profile = HotDataProfile(watched, versions, versions_to_keep=5)
    profile.start()
    try:
        yield profile, watched, versions
    finally:
        profile.stop()


def test_version_dir_inside_watched_path_raises(tmp_path):
    watched = tmp_path / "watched"
    watched.mkdir()
    with pytest.raises(ValueError):
        HotDataProfile(watched, watched / "versions", versions_to_keep=5)


def test_version_dir_equal_to_watched_path_raises(tmp_path):
    watched = tmp_path / "watched"
    watched.mkdir()
    with pytest.raises(ValueError):
        HotDataProfile(watched, watched, versions_to_keep=5)


def test_write_creates_a_version_snapshot(running_profile):
    profile, watched, versions = running_profile
    (watched / "file.txt").write_text("v1")

    assert wait_until(lambda: len(list(versions.glob("file.txt.*"))) >= 1)


def test_pruning_keeps_exactly_versions_to_keep(tmp_path):
    """The actual bug found and fixed: negative-index list slicing in
    _prune_versions silently capped history at 2 copies instead of the
    configured 5, regardless of how many distinct writes happened."""
    watched = tmp_path / "watched"
    versions = tmp_path / "watched.versions"
    watched.mkdir()
    profile = HotDataProfile(watched, versions, versions_to_keep=5)
    profile.start()
    try:
        target = watched / "file.txt"
        for i in range(7):
            target.write_text(f"version {i}")
            assert wait_until(lambda i=i: profile.last_event_type is not None and profile.last_event_at is not None)
            # Force a distinct snapshot filename per write - the version
            # filenames are second-resolution, and real-time writes in a tight
            # test loop can otherwise collide (a separate, already-fixed bug
            # class covered in test_staging.py, not what this test is about).
            time.sleep(1.05)
    finally:
        profile.stop()

    assert len(list(versions.glob("file.txt.*"))) == 5


def test_identical_content_does_not_create_duplicate_versions(running_profile):
    profile, watched, versions = running_profile
    target = watched / "file.txt"
    target.write_text("same content")
    assert wait_until(lambda: len(list(versions.glob("file.txt.*"))) >= 1)

    # Touching the file without changing its content (e.g. a duplicate
    # create+modify event pair, confirmed to happen on Windows) must not
    # waste a rollback slot on an identical copy.
    target.write_text("same content")
    time.sleep(0.3)
    assert len(list(versions.glob("file.txt.*"))) == 1


def test_delete_does_not_crash_and_is_logged(running_profile, app_log):
    profile, watched, versions = running_profile
    target = watched / "file.txt"
    target.write_text("v1")
    assert wait_until(lambda: len(list(versions.glob("file.txt.*"))) >= 1)

    target.unlink()
    assert wait_until(lambda: any("deleted" in m for m in app_log.messages()))
    # the last version taken before deletion is retained for rollback
    assert len(list(versions.glob("file.txt.*"))) == 1
