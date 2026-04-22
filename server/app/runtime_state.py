import json
from pathlib import Path


def write_runtime_state(file_path: Path, host: str, port: int) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(
            {
                'host': host,
                'port': port,
                'baseUrl': f'http://{host}:{port}',
            },
            indent=2,
        ),
        encoding='utf-8',
    )


def write_runtime_state_files(file_paths: list[Path], host: str, port: int) -> None:
    for file_path in file_paths:
        write_runtime_state(file_path, host, port)
