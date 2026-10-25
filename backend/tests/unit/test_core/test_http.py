from starlette.requests import Request

from app.core.http import client_ip


def _request(headers: dict[str, str], client: tuple[str, int] = ("9.9.9.9", 123)) -> Request:
    raw_headers = [(key.lower().encode(), value.encode()) for key, value in headers.items()]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": raw_headers,
            "client": client,
            "server": ("test", 80),
            "scheme": "http",
            "query_string": b"",
        }
    )


def test_prefers_trusted_real_ip_over_forwarded_for() -> None:
    request = _request(
        {
            "x-real-ip": "1.2.3.4",
            "x-forwarded-for": "6.6.6.6, 1.2.3.4",
        }
    )

    assert client_ip(request) == "1.2.3.4"


def test_falls_back_to_first_forwarded_ip() -> None:
    request = _request({"x-forwarded-for": "1.2.3.4, 10.0.0.1"})

    assert client_ip(request) == "1.2.3.4"


def test_falls_back_to_socket_client() -> None:
    assert client_ip(_request({})) == "9.9.9.9"
