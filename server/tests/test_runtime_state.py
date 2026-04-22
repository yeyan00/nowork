from pathlib import Path

from app.config import resolve_runtime_files


def test_resolve_runtime_files_uses_override_directory(tmp_path: Path) -> None:
    files = resolve_runtime_files(tmp_path)

    assert files[0].parent == tmp_path
    assert files[0].name == 'app-runtime.json'
