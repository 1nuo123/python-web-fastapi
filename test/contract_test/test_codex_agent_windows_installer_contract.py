"""Windows Agent MSI 源码和脚本发布契约。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parents[2]
PRODUCT_WXS = PROJECT_ROOT / "packaging" / "windows" / "wix" / "Product.wxs"
WINDOWS_SCRIPTS_ROOT = PROJECT_ROOT / "packaging" / "windows" / "scripts"
AGENT_SPEC = PROJECT_ROOT / "packaging" / "windows" / "agent.spec"


def test_wix_product_should_preserve_upgrade_and_uninstall_boundaries() -> None:
    content = PRODUCT_WXS.read_text("utf-8")

    assert 'Scope="perUser"' in content
    assert 'ProductCode="$(var.ProductCode)"' in content
    assert 'UpgradeCode="$(var.UpgradeCode)"' in content
    assert "<?define DeploymentProfile = production ?>" in content
    assert 'Name="Development"' in content
    assert 'AgentRegistryRoot = "CodexRemoteAgent\\Development"' in content
    assert 'AgentUriScheme = "codexremote-dev"' in content
    assert 'AgentProgramsFolderName = "Codex Remote Agent Development"' in content
    assert "AgentDevelopmentCertificateComponentGuid" in content
    assert 'Id="AgentDevelopmentCertificate"' in content
    assert 'Source="$(var.AgentSource)\\codex-dev-root-ca.crt"' in content
    assert "--deployment-profile development" in content
    assert "-DeploymentProfile $(var.DeploymentProfile)" in content
    assert "<MajorUpgrade" in content
    assert 'AllowSameVersionUpgrades="no"' in content
    assert 'Condition="REMOVE~=&quot;ALL&quot;"' in content
    assert "(NOT UPGRADINGPRODUCTCODE)" in content
    assert "[System64Folder]WindowsPowerShell" in content
    assert "[INSTALLFOLDER].&quot;" in content
    assert "agent-bootstrap.toml&quot; launch uri" in content
    assert '<Files Include="' not in content
    assert "$(var.IncludeTrustedRoot)" in content
    assert 'Source="$(var.AgentSource)\\root.json"' in content
    assert content.count('Key="Software\\$(var.AgentRegistryRoot)\\Components"') == 7
    assert "launch uri" in content
    assert "launch settings" in content
    assert "launch_agent.ps1" not in content


def test_development_installer_build_script_should_stage_isolated_tls_payload() -> None:
    script = (
        PROJECT_ROOT / "scripts" / "codex" / "build_development_agent_installer.ps1"
    ).read_text("utf-8")

    assert "agent_release_version" in script
    assert "json_schema_bundle_sha256" in script
    assert "--development-origin $DevelopmentOrigin" in script
    assert "codex-dev-root-ca.crt" in script
    assert "-d DeploymentProfile=development" in script
    assert "-d IncludeTrustedRoot=0" in script
    assert "CodexRemoteAgent.msi" in script
    assert '"ProductCode=$($installerIdentity.product_code)"' in script
    assert '"UpgradeCode=$($installerIdentity.upgrade_code)"' in script


def test_release_workflows_should_split_signed_build_from_verified_publish() -> None:
    build_workflow = (PROJECT_ROOT / ".github/workflows/codex-agent-release.yml").read_text("utf-8")
    publish_workflow = (PROJECT_ROOT / ".github/workflows/codex-agent-publish.yml").read_text(
        "utf-8"
    )
    sign_script = (WINDOWS_SCRIPTS_ROOT / "sign_release.ps1").read_text("utf-8")

    assert "uses: azure/login@v2" in build_workflow
    assert "uses: actions/setup-dotnet@v4" in build_workflow
    assert 'dotnet-version: "8.0.x"' in build_workflow
    assert build_workflow.index("uses: azure/login@v2") < build_workflow.index("sign_release.ps1")
    assert build_workflow.index("uses: actions/setup-dotnet@v4") < build_workflow.index(
        "sign_release.ps1"
    )
    assert "TUF_SIGNED_METADATA_ZIP_BASE64" not in build_workflow
    assert "az storage blob upload-batch" not in build_workflow
    assert "[IO.File]::WriteAllText(" in build_workflow
    assert "[Text.UTF8Encoding]::new($false)" in build_workflow
    assert "release-build.json -Encoding UTF8" not in build_workflow
    assert "signed_build_run_id" in publish_workflow
    assert "public_origin:" in publish_workflow
    assert '--public-origin "$env:PUBLIC_ORIGIN"' in publish_workflow
    assert "api_url:" not in publish_workflow
    assert "websocket_url:" not in publish_workflow
    assert "verification_url:" not in publish_workflow
    assert "website_url:" not in publish_workflow
    assert "getWorkflowRun" in publish_workflow
    assert "ref: ${{ steps.signed-build-run.outputs.head_sha }}" in publish_workflow
    assert "verify_codex_agent_tuf_metadata" in publish_workflow
    assert "--expected-source-revision" in publish_workflow
    assert "--expected-release-base-url" in publish_workflow
    assert "-d IncludeTrustedRoot=1" in publish_workflow
    assert "--release-manifest-target-path" not in publish_workflow
    assert "Stage consistent-snapshot repository layout" not in publish_workflow
    assert "Remove-Item -LiteralPath $plainTarget" not in publish_workflow
    assert "Remove-Item -LiteralPath $manifestTarget" not in publish_workflow
    assert publish_workflow.index("verify_codex_agent_tuf_metadata") < publish_workflow.index(
        "wix.exe build"
    )
    assert publish_workflow.index("uses: azure/login@v2") < publish_workflow.index(
        "sign_release.ps1"
    )
    assert "uses: actions/setup-dotnet@v4" in publish_workflow
    assert 'dotnet-version: "8.0.x"' in publish_workflow
    assert publish_workflow.index("uses: actions/setup-dotnet@v4") < publish_workflow.index(
        "sign_release.ps1"
    )
    assert "CODEX_AGENT_RELEASE_REPOSITORY_TOKEN" in publish_workflow
    assert "stage_codex_agent_release_repository" in publish_workflow
    assert "git -C dist/release-repository add --all" in publish_workflow
    assert 'push origin "HEAD:$env:RELEASE_BRANCH"' in publish_workflow
    assert "az storage blob upload" not in publish_workflow
    assert "azure_storage_account" not in publish_workflow
    assert publish_workflow.index("stage_codex_agent_release_repository") < publish_workflow.index(
        "git -C dist/release-repository commit"
    )
    assert "Test-Path -LiteralPath $toolExecutable" in sign_script
    assert "Get-Command az" in sign_script
    assert "account show --output none --only-show-errors" in sign_script
    assert "-kvm" in sign_script
    assert "-kva" not in sign_script
    assert "$LASTEXITCODE" in sign_script


def test_installer_scripts_should_isolate_user_task_and_purge_only_standard_root() -> None:
    register = (WINDOWS_SCRIPTS_ROOT / "register_task_scheduler.ps1").read_text("utf-8")
    unregister = (WINDOWS_SCRIPTS_ROOT / "unregister_task_scheduler.ps1").read_text("utf-8")
    purge = (WINDOWS_SCRIPTS_ROOT / "purge_agent_state.ps1").read_text("utf-8")

    assert '[ValidateSet("production", "development")]' in register
    assert '"CodexRemoteAgent$profileTaskSuffix-$currentUserSid"' in register
    assert 'if ($DeploymentProfile -eq "production")' in register
    assert '$arguments += "--deployment-profile", "development"' in register
    assert "-MultipleInstances IgnoreNew" in register
    assert "-RunLevel Limited" in register
    assert '"CodexRemoteAgent$profileTaskSuffix-$currentUserSid"' in unregister
    assert 'if ($DeploymentProfile -eq "production")' in unregister
    assert "ExecutablePath" in unregister
    assert '[ValidateSet("production", "development")]' in purge
    assert 'Join-Path $productionRoot "Development"' in purge
    assert '"codex-dev-root-ca.crt"' in purge
    assert "Refusing to purge a non-standard Agent data directory." in purge
    assert "$packageFiles" in purge
    assert "Get-ChildItem -LiteralPath $resolvedInstallRoot -Force" in purge
    assert "[IO.FileAttributes]::ReparsePoint" in purge
    assert '"launch", "run"' in register
    assert "-Execute $resolvedExecutablePath" in register


@pytest.mark.skipif(os.name != "nt", reason="PowerShell uninstall behavior is Windows-only.")
def test_purge_script_should_remove_all_dynamic_state_and_preserve_package_files(
    tmp_path: Path,
) -> None:
    local_app_data = tmp_path / "LocalAppData"
    install_root = local_app_data / "CodexRemoteAgent"
    install_root.mkdir(parents=True)
    package_files = (
        "codex-remote-agent.exe",
        "agent-bootstrap.toml",
        "codex-dev-root-ca.crt",
        "register_task_scheduler.ps1",
        "unregister_task_scheduler.ps1",
        "purge_agent_state.ps1",
        "root.json",
    )
    for file_name in package_files:
        (install_root / file_name).write_text("package", encoding="utf-8")
    for file_name in (
        "agent.toml",
        "custom.lock",
        "custom-state.sqlite",
        "custom-state.sqlite-shm",
        "custom-state.sqlite-wal",
        "agent.stdout.log",
        "agent.stderr.log",
    ):
        (install_root / file_name).write_text("dynamic", encoding="utf-8")
    for directory_name in ("keys", "logs", "releases", "future-state"):
        directory = install_root / directory_name
        directory.mkdir()
        (directory / "state.bin").write_bytes(b"dynamic")
    environment = os.environ.copy()
    environment["LOCALAPPDATA"] = str(local_app_data)

    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(WINDOWS_SCRIPTS_ROOT / "purge_agent_state.ps1"),
            "-InstallRoot",
            str(install_root),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr
    assert {path.name for path in install_root.iterdir()} == set(package_files)


@pytest.mark.skipif(os.name != "nt", reason="PowerShell uninstall behavior is Windows-only.")
def test_development_purge_script_should_not_remove_production_state(tmp_path: Path) -> None:
    """开发卸载只能清理 Development，绝不能触及同级生产目录。"""

    local_app_data = tmp_path / "LocalAppData"
    production_root = local_app_data / "CodexRemoteAgent"
    development_root = production_root / "Development"
    development_root.mkdir(parents=True)
    for file_name in (
        "codex-remote-agent.exe",
        "agent-bootstrap.toml",
        "codex-dev-root-ca.crt",
        "register_task_scheduler.ps1",
        "unregister_task_scheduler.ps1",
        "purge_agent_state.ps1",
        "root.json",
    ):
        (development_root / file_name).write_text("package", encoding="utf-8")
    (development_root / "agent.toml").write_text("development", encoding="utf-8")
    production_root.mkdir(exist_ok=True)
    production_sentinel = production_root / "agent.toml"
    production_sentinel.write_text("production", encoding="utf-8")
    environment = os.environ.copy()
    environment["LOCALAPPDATA"] = str(local_app_data)

    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(WINDOWS_SCRIPTS_ROOT / "purge_agent_state.ps1"),
            "-InstallRoot",
            str(development_root),
            "-DeploymentProfile",
            "development",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr
    assert production_sentinel.read_text(encoding="utf-8") == "production"
    assert not (development_root / "agent.toml").exists()
    assert (development_root / "codex-remote-agent.exe").exists()


def test_pyinstaller_spec_should_build_one_file_windowed_executable() -> None:
    content = AGENT_SPEC.read_text("utf-8")

    assert "a.binaries" in content
    assert "a.datas" in content
    assert "console=False" in content
    assert 'os.environ["CODEX_AGENT_VERSION_FILE"]' in content
    assert "version=version_file" in content
    assert "COLLECT(" not in content
