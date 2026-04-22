import socket

from app.port_resolver import choose_port


def _find_consecutive_free_ports(host: str) -> tuple[int, int]:
    for port in range(20000, 40000):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as first_sock:
            try:
                first_sock.bind((host, port))
            except OSError:
                continue

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as second_sock:
                try:
                    second_sock.bind((host, port + 1))
                except OSError:
                    continue

            return port, port + 1

    raise RuntimeError('Could not find consecutive free ports for test')


def test_choose_port_returns_requested_port_when_free() -> None:
    port = choose_port(host='127.0.0.1', preferred_port=18080, max_attempts=3)

    assert isinstance(port, int)
    assert port >= 18080


def test_choose_port_falls_forward_when_preferred_port_is_occupied() -> None:
    preferred_port, expected_port = _find_consecutive_free_ports('127.0.0.1')

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', preferred_port))
        sock.listen(1)

        port = choose_port(host='127.0.0.1', preferred_port=preferred_port, max_attempts=3)

    assert port == expected_port
