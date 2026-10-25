from mcp.server.transport_security import TransportSecurityMiddleware

from mcp_server.server import mcp


def test_internal_service_host_is_allowed() -> None:
    settings = mcp.settings.transport_security
    assert settings is not None
    assert settings.enable_dns_rebinding_protection is True

    middleware = TransportSecurityMiddleware(settings)
    assert middleware._validate_host("mcp-server:8001") is True
    assert middleware._validate_host("127.0.0.1:8001") is True
    assert middleware._validate_host("evil.example.com") is False
