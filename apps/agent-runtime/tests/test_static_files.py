from pathlib import Path

from app.static_files import resolve_static_file


def test_resolve_static_file_rejects_parent_directory_escape(tmp_path: Path) -> None:
    static_dir = tmp_path / "out"
    static_dir.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")

    assert resolve_static_file(static_dir, "../secret.txt") is None


def test_resolve_static_file_allows_file_under_static_dir(tmp_path: Path) -> None:
    static_dir = tmp_path / "out"
    static_dir.mkdir()
    index = static_dir / "archive" / "index.html"
    index.parent.mkdir()
    index.write_text("<html></html>", encoding="utf-8")

    assert resolve_static_file(static_dir, "archive/index.html") == index.resolve()
