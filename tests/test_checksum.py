import hashlib

from engine.checksum import compute_checksum


def test_matches_known_hash(tmp_path):
    path = tmp_path / "file.txt"
    path.write_bytes(b"hello world")
    expected = hashlib.sha256(b"hello world").hexdigest()
    assert compute_checksum(path) == expected


def test_missing_file_returns_none(tmp_path):
    assert compute_checksum(tmp_path / "does-not-exist.txt") is None


def test_different_content_different_checksum(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_bytes(b"one")
    b.write_bytes(b"two")
    assert compute_checksum(a) != compute_checksum(b)
