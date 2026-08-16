"""Caddy Docker gateway deployment contract tests."""

from pathlib import Path


def test_caddy_template_should_proxy_same_origin_without_secrets() -> None:
    content = (Path(__file__).parents[2] / "deploy/caddy/Caddyfile.example").read_text(
        encoding="utf-8"
    )

    assert "reverse_proxy frontend:3000" in content
    assert "reverse_proxy @backend app:8000" in content
    assert "reverse_proxy @codex_events app:8000" in content
    assert "/codex/*" not in content
    assert content.index("reverse_proxy @codex_events") < content.index(
        "reverse_proxy frontend:3000"
    )
    assert content.index("reverse_proxy @backend") < content.index("reverse_proxy frontend:3000")
    for forbidden in ("access_token", "refresh_token", "api_key", "Authorization:"):
        assert forbidden not in content


def test_caddy_compose_should_keep_gateway_state_separate() -> None:
    content = (Path(__file__).parents[2] / "deploy/caddy/compose.yml").read_text(encoding="utf-8")

    assert "caddy:2.10.2-alpine" in content
    assert "fastapi-web-edge" in content
    assert "caddy_data:/data" in content
    assert "caddy_config:/config" in content
    assert "NET_BIND_SERVICE" in content
    assert "read_only: true" in content


def test_caddy_operations_document_should_require_https_acceptance() -> None:
    content = (Path(__file__).parents[2] / "deploy/caddy/README.md").read_text(encoding="utf-8")

    assert "docker network create" in content
    assert "https://" in content
    assert "network switch" in content
    assert "snapshot" in content
