from pathlib import Path

from app.static_files import resolve_spa_static_file, resolve_static_file


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


def test_resolve_spa_static_file_uses_project_shell_for_dynamic_project_path(tmp_path: Path) -> None:
    static_dir = tmp_path / "out"
    project_shell = static_dir / "p" / "__placeholder__" / "index.html"
    project_shell.parent.mkdir(parents=True)
    project_shell.write_text("<html>project shell</html>", encoding="utf-8")
    index = static_dir / "index.html"
    index.write_text("<html>home</html>", encoding="utf-8")

    assert resolve_spa_static_file(static_dir, "p/task_prod_fixture") == project_shell.resolve()


def test_resolve_spa_static_file_keeps_regular_static_index_resolution(tmp_path: Path) -> None:
    static_dir = tmp_path / "out"
    archive_index = static_dir / "archive" / "index.html"
    archive_index.parent.mkdir(parents=True)
    archive_index.write_text("<html>archive</html>", encoding="utf-8")
    home_index = static_dir / "index.html"
    home_index.write_text("<html>home</html>", encoding="utf-8")

    assert resolve_spa_static_file(static_dir, "archive") == archive_index.resolve()
