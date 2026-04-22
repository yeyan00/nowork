import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import get_log_dir, get_server_config

_logger_initialized = False


def setup_logging(cfg: dict | None = None) -> None:
    global _logger_initialized
    if _logger_initialized:
        return
    _logger_initialized = True

    log_dir = get_log_dir(cfg)
    log_file = log_dir / 'nowork-server.log'

    server = get_server_config(cfg)
    log_level_name = server.get('log_level', 'INFO').upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    root = logging.getLogger()
    root.setLevel(log_level)

    fmt = logging.Formatter(
        '%(asctime)s %(levelname)-7s [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(log_level)
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        str(log_file),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding='utf-8',
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    logging.getLogger('nowork').info('Logging initialized: %s (level=%s)', log_file, log_level_name)


def get_logger(name: str = 'nowork') -> logging.Logger:
    return logging.getLogger(name)
