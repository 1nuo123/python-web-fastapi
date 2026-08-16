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


def test_ip_production_scripts_should_keep_gateway_and_secrets_consistent() -> None:
    project_root = Path(__file__).parents[2]
    prepare_script = (project_root / "deploy/prepare-production-env.sh").read_text(encoding="utf-8")
    run_script = (project_root / "deploy/run-production-ip.sh").read_text(encoding="utf-8")
    security_config = (
        project_root / "config/runtime/security_runtime/security_runtime_production.toml"
    ).read_text(encoding="utf-8")
    stream_config = (
        project_root / "config/runtime/stream_runtime/stream_runtime_production.toml"
    ).read_text(encoding="utf-8")

    assert "openssl rand -hex" in prepare_script
    assert ".env.initial-admin.local" in prepare_script
    assert "INITIAL_ADMIN_USERNAME=admin" in prepare_script
    assert 'EDGE_NETWORK_SUBNET="172.30.0.0/24"' in run_script
    assert "--env-from-file" in run_script
    assert "task-worker" not in run_script
    assert 'trusted_proxy_cidr_blocks = ["172.30.0.0/24"]' in security_config
    assert '"http://47.113.177.140"' in stream_config
    assert "localhost" not in stream_config
