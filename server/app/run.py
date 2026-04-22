import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn

from app.config import load_config, get_server_config, resolve_runtime_files
from app.log import setup_logging
from app.main import app
from app.port_resolver import choose_port
from app.runtime_state import write_runtime_state_files


def main() -> None:
    cfg = load_config()
    server = get_server_config(cfg)
    host = server.get('host', '127.0.0.1')
    preferred_port = server.get('port', 18080)

    setup_logging(cfg)

    port = choose_port(
        host=host,
        preferred_port=preferred_port,
        max_attempts=20,
    )
    write_runtime_state_files(resolve_runtime_files(), host, port)
    uvicorn.run(app, host=host, port=port)


if __name__ == '__main__':
    main()
