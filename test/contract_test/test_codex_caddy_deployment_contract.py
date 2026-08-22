"""Caddy Docker gateway deployment contract tests."""

import shlex
import subprocess
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
    assert content.count("header_up -Forwarded") == 3


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


def test_development_caddy_profile_should_use_internal_tls_and_a_separate_edge() -> None:
    """开发 HTTPS 必须有独立网关、域名和内部 CA，不能复用生产入口。"""

    project_root = Path(__file__).parents[2]
    caddyfile = (project_root / "deploy/caddy/Caddyfile.development.example").read_text(
        encoding="utf-8"
    )
    compose = (project_root / "deploy/caddy/compose.development.yml").read_text(encoding="utf-8")
    stream_config = (
        project_root / "config/runtime/stream_runtime/stream_runtime_development.toml"
    ).read_text(encoding="utf-8")
    web_config = (
        project_root / "config/runtime/web_runtime/web_runtime_development.toml"
    ).read_text(encoding="utf-8")
    security_config = (
        project_root / "config/runtime/security_runtime/security_runtime_development.toml"
    ).read_text(encoding="utf-8")

    assert "{$CADDY_DEV_SITE_ADDRESS:codex-dev.lan}" in caddyfile
    assert "tls internal" in caddyfile
    assert "reverse_proxy @codex_events app:8000" in caddyfile
    assert caddyfile.count("header_up -Forwarded") == 3
    assert "fastapi-web-development-edge" in compose
    assert "gateway: {}" in compose
    assert "caddy_development_data:/data" in compose
    assert '"https://codex-dev.lan"' in stream_config
    assert '"https://codex-dev.lan"' in web_config
    assert (
        'trusted_proxy_cidr_blocks = ["127.0.0.0/8", "::1/128", "172.32.0.0/24"]' in security_config
    )


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
    assert (
        'PRODUCTION_CODEX_FEATURE_ENABLED="${PRODUCTION_CODEX_FEATURE_ENABLED:-false}"'
        in prepare_script
    )
    assert 'case "$PRODUCTION_CODEX_FEATURE_ENABLED" in' in prepare_script
    assert "true|false) ;;" in prepare_script
    assert "PRODUCTION_CODEX_FEATURE_ENABLED must be true or false." in prepare_script
    assert "NUXT_PUBLIC_CODEX_FEATURE_ENABLED=$PRODUCTION_CODEX_FEATURE_ENABLED" in prepare_script
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


def test_prepare_production_environment_should_disable_codex_by_default_and_validate_override(
    tmp_path: Path,
) -> None:
    """生产初始化必须以故障关闭策略生成前端 Codex 开关。"""

    project_root = Path(__file__).parents[2]
    source_script = project_root / "deploy/prepare-production-env.sh"

    def run_prepare(feature_enabled: str | None) -> subprocess.CompletedProcess[str]:
        profile = feature_enabled if feature_enabled is not None else "default"
        backend_root = tmp_path / f"backend-{profile}"
        script_root = backend_root / "deploy"
        script_root.mkdir(parents=True)
        script_path = script_root / source_script.name
        script_path.write_bytes(source_script.read_bytes())
        script_path.chmod(0o755)
        frontend_root = backend_root.parent / f"frontend-{backend_root.name}"
        frontend_root.mkdir()
        command = ["bash", f"./deploy/{source_script.name}", f"../{frontend_root.name}"]
        if feature_enabled is not None:
            prepare_command = shlex.join(
                [f"./deploy/{source_script.name}", f"../{frontend_root.name}"]
            )
            command = [
                "bash",
                "-c",
                f"export PRODUCTION_CODEX_FEATURE_ENABLED={shlex.quote(feature_enabled)}; exec {prepare_command}",
            ]
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            cwd=backend_root,
            text=True,
        )

    default_result = run_prepare(None)
    assert default_result.returncode == 0, default_result.stderr
    default_environment = (tmp_path / "frontend-backend-default/.env.production.local").read_text(
        encoding="utf-8"
    )
    assert "NUXT_PUBLIC_CODEX_FEATURE_ENABLED=false" in default_environment

    enabled_result = run_prepare("true")
    assert enabled_result.returncode == 0, enabled_result.stderr
    enabled_environment = (tmp_path / "frontend-backend-true/.env.production.local").read_text(
        encoding="utf-8"
    )
    assert "NUXT_PUBLIC_CODEX_FEATURE_ENABLED=true" in enabled_environment

    invalid_result = run_prepare("enabled")
    assert invalid_result.returncode != 0
    assert "PRODUCTION_CODEX_FEATURE_ENABLED must be true or false." in invalid_result.stderr


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
    assert "Codex Remote 发布门禁" in guide
    assert "PRODUCTION_CODEX_FEATURE_ENABLED=true bash deploy/production.sh bootstrap" in guide
    assert "Authenticode 签名、TUF 发布元数据" in guide
    assert "docker compose down -v" in guide
