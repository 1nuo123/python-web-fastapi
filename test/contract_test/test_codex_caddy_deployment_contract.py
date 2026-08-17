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


def test_production_scripts_should_keep_gateway_and_secrets_consistent() -> None:
    project_root = Path(__file__).parents[2]
    prepare_script = (project_root / "deploy/prepare-production-env.sh").read_text(encoding="utf-8")
    run_script = (project_root / "deploy/run-production-ip.sh").read_text(encoding="utf-8")
    operations_script = (project_root / "deploy/production.sh").read_text(encoding="utf-8")
    security_config = (
        project_root / "config/runtime/security_runtime/security_runtime_production.toml"
    ).read_text(encoding="utf-8")
    stream_config = (
        project_root / "config/runtime/stream_runtime/stream_runtime_production.toml"
    ).read_text(encoding="utf-8")

    assert "openssl rand -hex" in prepare_script
    assert ".env.initial-admin.local" in prepare_script
    assert "INITIAL_ADMIN_USERNAME=admin" in prepare_script
    assert 'PRODUCTION_SITE_ADDRESS="${PRODUCTION_SITE_ADDRESS:-nuotop.xyz}"' in prepare_script
    assert 'EDGE_NETWORK_SUBNET="172.30.0.0/24"' in run_script
    assert "--env-from-file" in run_script
    assert "PRODUCTION_BOOTSTRAP_ADMIN:-0" in run_script
    assert "--project-name fastapi-web-production" in run_script
    assert "docker curl awk" in run_script
    assert '--resolve "${site_address%/}:443:127.0.0.1"' in run_script
    assert "task-worker" not in run_script
    assert "pg_dump -Fc" in operations_script
    assert 'git -C "$BACKEND_ROOT" merge --ff-only origin/main' in operations_script
    assert "docker system df" in operations_script
    assert "load_readiness_target" in operations_script
    assert "down -v" not in operations_script
    assert 'trusted_proxy_cidr_blocks = ["172.30.0.0/24"]' in security_config
    assert '"https://nuotop.xyz"' in stream_config
    assert "localhost" not in stream_config


def test_production_compose_should_persist_runtime_state_and_rotate_logs() -> None:
    project_root = Path(__file__).parents[2]
    production_compose = (project_root / "compose.production.yml").read_text(encoding="utf-8")
    caddy_compose = (project_root / "deploy/caddy/compose.yml").read_text(encoding="utf-8")

    assert "redis_data:/data" in production_compose
    assert "rabbitmq_data:/var/lib/rabbitmq" in production_compose
    assert '"--appendonly"' in production_compose
    assert 'max-size: "20m"' in production_compose
    assert "max-size: '20m'" in caddy_compose


def test_production_operations_guide_should_cover_full_lifecycle() -> None:
    project_root = Path(__file__).parents[2]
    guide = (project_root / "docs/生产环境Docker一键部署与长期运维指南.md").read_text(
        encoding="utf-8"
    )

    for required_command in (
        "bash deploy/production.sh bootstrap",
        "bash deploy/production.sh update",
        "bash deploy/production.sh backup",
        "bash deploy/production.sh status",
    ):
        assert required_command in guide
    assert "数据库恢复" in guide
    assert "应用回滚" in guide
    assert "正式域名与 HTTPS 启用" in guide
    assert "docker compose down -v" in guide
