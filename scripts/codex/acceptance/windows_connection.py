"""真实HTTPS/WSS + 产品组合根 + Windows Codex进程的隔离端到端故障验收。

仅使用本机临时SQLite/内存总线，不能替代Redis多实例、真实边缘代理和睡眠验收。
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
import psutil
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from src.api.testing.test_app_factory import TestAppFactory
from src.core.codex_contract.agent_protocol_contract import CodexAgentCommand
from src.core.codex_contract.connection_session_contract import CodexHostOfflineError
from src.core.http_contract.outbound_http_client_contract import AsyncHttpClientDetail
from src.domain.codex.agent_command_policy import calculate_agent_request_digest
from src.infrastructure.codex_agent.agent_command_journal import AgentCommandJournal
from src.infrastructure.codex_agent.agent_config_store import AgentConfigStore
from src.infrastructure.codex_agent.agent_configuration import (
    AgentBootstrapSettings,
    CodexHostAgentSettings,
)
from src.infrastructure.codex_agent.agent_connection_ticket_provider import (
    AgentConnectionTicketProvider,
)
from src.infrastructure.codex_agent.agent_control_channel import AgentControlChannel
from src.infrastructure.codex_agent.agent_network_policy import AgentNetworkPolicy
from src.infrastructure.codex_agent.agent_runtime_status_store import AgentRuntimeStatusStore
from src.infrastructure.codex_agent.agent_secret_store import WindowsAgentSecretStore
from src.infrastructure.codex_agent.agent_workspace_registry import AgentWorkspaceRegistry
from src.infrastructure.codex_agent.windows_dpapi_device_key_store import (
    WindowsCurrentUserAclEnforcer,
    WindowsCurrentUserDpapi,
    WindowsDpapiDeviceKeyStore,
)
from src.infrastructure.resource_slot.shared_async_http_client import SharedAsyncHttpClient
from test.fixtures.codex_device_authorization_test_support import (
    CodexDeviceAuthorizationTestSupport as DeviceSupport,
)


class FaultBoundary:
    """只在真实网络入口注入失败，不替换产品连接、鉴权或执行实现。"""

    def __init__(self, app):
        self.app = app
        self.failures = {}
        self.delay_next_ws_send = 0.0
        self.send_delay_active = False
        self.injected = []
        self.tickets = set()
        self.ticket_reuse = 0
        self.auth_requests = 0
        self.consume_next_ticket = True
        self.websocket_peers = []
        self.auth_peers = []

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] == "websocket":
            self.websocket_peers.append(tuple(scope["client"]))
            digest = hashlib.sha256(scope.get("query_string", b"")).hexdigest()
            self.ticket_reuse += int(digest in self.tickets)
            self.tickets.add(digest)
        if path in (
            "/internal/codex-agents/device-challenges",
            "/internal/codex-agents/connection-tickets",
        ):
            self.auth_requests += 1
            self.auth_peers.append(tuple(scope["client"]))
        failures = self.failures.get(path, [])
        if failures and scope["type"] in ("http", "websocket"):
            status = failures.pop(0)
            self.injected.append({"path": path, "status": status})
            prefix = "websocket.http.response" if scope["type"] == "websocket" else "http.response"
            await receive()
            await send(
                {
                    "type": prefix + ".start",
                    "status": status,
                    "headers": [(b"content-type", b"text/html")],
                }
            )
            await send({"type": prefix + ".body", "body": b"controlled upstream outage"})
            return
        if scope["type"] == "websocket" and self.consume_next_ticket:
            self.consume_next_ticket = False
            runtime = self.app.state.container.resource_mount.get_codex_control_runtime()
            ticket = parse_qs(scope["query_string"].decode("ascii"))["ticket"][0]
            await runtime.consume_agent_connection_ticket.execute(
                ticket=ticket,
                client_ip=scope["client"][0],
            )
            self.injected.append({"path": path, "status": 401, "reason": "ticket_expired"})

        async def delayed_send(message):
            if message["type"] == "websocket.send" and self.delay_next_ws_send:
                delay, self.delay_next_ws_send = self.delay_next_ws_send, 0.0
                self.send_delay_active = True
                try:
                    await asyncio.sleep(delay)
                finally:
                    self.send_delay_active = False
            await send(message)

        await self.app(scope, receive, delayed_send)


def certificate(directory):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "agent-loopback-acceptance")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=4))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    certpath, keypath = directory / "ca.pem", directory / "tls.key"
    certpath.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    keypath.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return certpath, keypath


async def until(predicate, *, timeout=90, task=None):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if task is not None and task.done():
            await task
            raise AssertionError("Agent运行循环提前结束")
        if asyncio.get_running_loop().time() >= deadline:
            for pending in asyncio.all_tasks():
                print(
                    "acceptance pending",
                    pending.get_name(),
                    [f"{frame.f_code.co_name}:{frame.f_lineno}" for frame in pending.get_stack()],
                )
            raise TimeoutError("端到端条件未在截止时间内成立")
        await asyncio.sleep(0.1)


async def binary_acceptance(directory, settings, app, boundary, report):
    import rtoml

    from src.infrastructure.codex_agent.agent_deployment_profile import AgentDeploymentProfile

    settings = settings.model_copy(
        update={
            "agent": settings.agent.model_copy(
                update={"deployment_profile": AgentDeploymentProfile.PRODUCTION}
            )
        }
    )
    executable = Path(
        next(
            (arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--executable=")),
            str(ROOT / "dist/codex-remote-agent.exe"),
        )
    )
    assert executable.is_file()
    config = directory / "agent.toml"
    store = AgentConfigStore(config, WindowsCurrentUserAclEnforcer())
    store.write(store.serialize(settings))
    from src.infrastructure.codex_agent.agent_executable_selector import (
        WindowsAgentFileVersionReader,
    )

    bootstrap = AgentBootstrapSettings(
        deployment_state="unconfigured",
        connection=None,
        agent_version=WindowsAgentFileVersionReader().read(executable),
        expected_codex_version="0.145.0",
        app_server_schema_digest=settings.protocol.app_server_schema_digest,
    )
    bootpath = directory / "agent-bootstrap.toml"
    bootpath.write_text(
        rtoml.dumps(bootstrap.model_dump(mode="json", exclude_none=True)), encoding="utf-8"
    )
    args = (str(executable), "--config", str(config), "--bootstrap", str(bootpath), "launch", "run")
    if "--pause-only" in sys.argv:
        runtime = app.state.container.resource_mount.get_codex_control_runtime()
        status_store = AgentRuntimeStatusStore(settings.agent.state_database)
        await scheduler_acceptance(args, directory, settings, runtime, status_store, report)
        report["executable_sha256"] = hashlib.sha256(executable.read_bytes()).hexdigest()
        return
    boundary.failures = {
        "/internal/codex-agents/device-challenges": [520],
        "/internal/codex-agents/connection-tickets": [522],
        "/internal/codex-agents/connect": [520],
    }
    process = await asyncio.create_subprocess_exec(*args)
    owned_processes = [process]
    waiting = asyncio.create_task(process.wait())
    runtime = app.state.container.resource_mount.get_codex_control_runtime()
    status_store = AgentRuntimeStatusStore(settings.agent.state_database)
    pid = None
    try:

        def ready():
            lease = runtime.connection_registry._leases.get(settings.agent.host_id)
            return lease is not None and lease.sender._confirmed_generation is not None

        await until(ready, timeout=120, task=waiting)
        status = status_store.read()
        assert status is not None and status.process_id
        pid = status.process_id
        descendants = psutil.Process(pid).children(recursive=True)
        assert descendants
        report["scenarios"].append(
            {
                "name": "packaged EXE recovers 520/522 and reaches server command-ready",
                "passed": True,
                "agent_pid": pid,
            }
        )
        assert any(item.get("reason") == "ticket_expired" for item in boundary.injected)
        report["scenarios"].append(
            {"name": "packaged EXE retries consumed ticket with fresh credentials", "passed": True}
        )
        auth_before = boundary.auth_requests
        doctor = await asyncio.create_subprocess_exec(
            str(executable), "--config", str(config), "doctor"
        )
        owned_processes.append(doctor)
        code = await asyncio.wait_for(doctor.wait(), 60)
        assert code in (0, 10), code
        assert boundary.auth_requests == auth_before
        report["scenarios"].append(
            {
                "name": "packaged doctor uses configured CA and does not issue device credentials",
                "passed": True,
                "exit_code": code,
            }
        )
        duplicate = await asyncio.create_subprocess_exec(*args)
        owned_processes.append(duplicate)
        code = await asyncio.wait_for(duplicate.wait(), 30)
        assert code != 0 and psutil.pid_exists(pid)
        report["scenarios"].append(
            {"name": "packaged duplicate run rejected by existing singleton lock", "passed": True}
        )
        psutil.Process(pid).kill()
        await until(lambda: not any(child.is_running() for child in descendants), timeout=15)
        await asyncio.wait_for(waiting, 20)
        stale = status_store.read()
        assert stale is not None and stale.connection_state == "stopped"
        report["scenarios"].append(
            {
                "name": "actual Agent crash kills owned process tree; stale online projection invalidated",
                "passed": True,
                "owned_process_count": len(descendants),
            }
        )
        report["executable_sha256"] = hashlib.sha256(executable.read_bytes()).hexdigest()
        report["ticket_reuse"] = boundary.ticket_reuse
        if "--scheduler" in sys.argv:
            await scheduler_acceptance(args, directory, settings, runtime, status_store, report)
    finally:
        log = directory / "logs/agent.log"
        if log.exists():
            (ROOT / ".codex-validation-logs/binary-agent.log").write_bytes(log.read_bytes())
        report["process_exit_code"] = process.returncode
        for owned in reversed(owned_processes):
            if owned.returncode is not None:
                continue
            try:
                parent = psutil.Process(owned.pid)
                children = parent.children(recursive=True)
                for child in reversed(children):
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass
                parent.kill()
            except psutil.NoSuchProcess:
                pass
            await asyncio.wait_for(owned.wait(), 15)
        await asyncio.gather(waiting, return_exceptions=True)


async def scheduler_acceptance(args, directory, settings, runtime, status_store, report):
    """复制现有托管策略到隔离任务，结束后删除；不修改用户安装的任务。"""
    from src.infrastructure.codex_agent.windows_agent_task import (
        PsutilWindowsAgentRunProcessBackend,
        WindowsAgentTaskController,
    )

    task_name = f"CodexRemoteAgent-Acceptance-{uuid4().hex}"
    process_backend = PsutilWindowsAgentRunProcessBackend(
        config_path=directory / "agent.toml",
        executable_path=Path(args[0]),
    )
    controller = WindowsAgentTaskController(
        task_name=task_name, run_process_backend=process_backend
    )
    env = {
        **os.environ,
        "AGENT_ACCEPTANCE_TASK": task_name,
        "AGENT_ACCEPTANCE_EXE": args[0],
        "AGENT_ACCEPTANCE_ARGS": subprocess.list2cmdline(args[1:]),
        "AGENT_ACCEPTANCE_DIRECTORY": str(directory),
    }

    async def powershell(script):
        process = await asyncio.create_subprocess_exec(
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "$ErrorActionPreference='Stop'; " + script,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), 30)
        except BaseException:
            process.kill()
            await process.wait()
            raise
        if process.returncode != 0:
            raise RuntimeError(
                f"Isolated Task Scheduler action failed: {stderr.decode(errors='replace')}"
            )
        return stdout

    def ready_pid(excluded):
        status = status_store.read()
        lease = runtime.connection_registry._leases.get(settings.agent.host_id)
        return (
            status is not None
            and status.process_id not in excluded
            and status.connection_state == "online"
            and lease is not None
            and lease.sender._confirmed_generation is not None
        )

    try:
        await powershell("""
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
[xml]$definition = Export-ScheduledTask -TaskName ('CodexRemoteAgent-' + $sid)
$definition.Task.Actions.Exec.Command = $env:AGENT_ACCEPTANCE_EXE
$definition.Task.Actions.Exec.Arguments = $env:AGENT_ACCEPTANCE_ARGS
$definition.Task.Actions.Exec.WorkingDirectory = $env:AGENT_ACCEPTANCE_DIRECTORY
$definition.Task.RegistrationInfo.URI = '\\' + $env:AGENT_ACCEPTANCE_TASK
Register-ScheduledTask -TaskName $env:AGENT_ACCEPTANCE_TASK -Xml $definition.OuterXml | Out-Null
Start-ScheduledTask -TaskName $env:AGENT_ACCEPTANCE_TASK
""")
        await until(lambda: ready_pid({None}), timeout=90)
        if "--pause-only" not in sys.argv:
            before = status_store.read().process_id
            report["scheduler_initial_pid"] = before
            await asyncio.sleep(35)
            await asyncio.sleep(30)
            assert ready_pid({None}) and status_store.read().process_id == before
            report["scenarios"].append(
                {
                    "name": "periodic OS trigger preserves the healthy Agent PID with IgnoreNew",
                    "passed": True,
                }
            )
            children = psutil.Process(before).children(recursive=True)
            psutil.Process(before).kill()
            await until(lambda: not any(child.is_running() for child in children), timeout=15)
            await until(lambda: ready_pid({None, before}), timeout=180)
            report["scenarios"].append(
                {
                    "name": "Task Scheduler restarts crashed packaged Agent using existing policy",
                    "passed": True,
                }
            )
        current = status_store.read().process_id
        children = psutil.Process(current).children(recursive=True)
        await asyncio.to_thread(controller.pause)
        assert controller.read_status().state == "Disabled"
        await until(
            lambda: (
                not psutil.pid_exists(current) and not any(child.is_running() for child in children)
            ),
            timeout=20,
        )
        await asyncio.sleep(35)
        await asyncio.sleep(30)
        assert status_store.read().connection_state == "stopped"
        assert not ready_pid({None})
        report["scenarios"].append(
            {
                "name": "explicit Task Scheduler pause remains stopped beyond restart interval; no orphan processes",
                "passed": True,
            }
        )
        await asyncio.to_thread(controller.start)
        await until(lambda: ready_pid({None, current}), timeout=90)
        report["scenarios"].append(
            {
                "name": "explicit resume enables the same task and restores command-ready",
                "passed": True,
            }
        )
    finally:
        report["scheduler_last_state"] = (
            (
                await powershell("""
$task = Get-ScheduledTask -TaskName $env:AGENT_ACCEPTANCE_TASK -ErrorAction SilentlyContinue
if ($null -ne $task) {
  $info = Get-ScheduledTaskInfo -TaskName $env:AGENT_ACCEPTANCE_TASK
  [pscustomobject]@{state=$task.State.ToString(); result=$info.LastTaskResult; last_run=$info.LastRunTime.ToUniversalTime().ToString('o')} | ConvertTo-Json -Compress
}
""")
            )
            .decode(errors="replace")
            .strip()
        )
        await powershell("""
$task = Get-ScheduledTask -TaskName $env:AGENT_ACCEPTANCE_TASK -ErrorAction SilentlyContinue
if ($null -ne $task) {
  Stop-ScheduledTask -TaskName $env:AGENT_ACCEPTANCE_TASK
  Unregister-ScheduledTask -TaskName $env:AGENT_ACCEPTANCE_TASK -Confirm:$false
}
""")
        await asyncio.to_thread(process_backend.stop_all)


async def main():
    candidate_path = next(
        (arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--connection-candidate=")),
        None,
    )
    candidate = (
        tomllib.loads(Path(candidate_path).read_text(encoding="utf-8")) if candidate_path else {}
    )
    proxy_kind = next(
        (arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--proxy=")), None
    )
    if proxy_kind not in (None, "http", "https", "system"):
        raise ValueError("Unsupported proxy scenario")
    rejection = next(
        (arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--rejection=")), None
    )
    if rejection not in (None, "403", "525", "526", "tls"):
        raise ValueError("Unsupported rejection scenario")
    report = {
        "environment": "Windows; real TLS/WSS; product ASGI routes; SQLite/local bus; real Codex 0.145.0",
        "scenarios": [],
    }
    output = (
        ROOT
        / "test-results/windows-agent-connection-implementation"
        / (
            "scheduler-pause.json"
            if "--pause-only" in sys.argv
            else "scheduler.json"
            if "--scheduler" in sys.argv
            else "binary.json"
            if "--binary" in sys.argv
            else "mutation.json"
            if "--mutation-only" in sys.argv
            else "runtime-recovery.json"
            if "--runtime-recovery" in sys.argv
            else "acceptance.json"
        )
    )
    output = Path(
        next(
            (arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--acceptance-report=")),
            str(output),
        )
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    if rejection is not None:
        output = output.with_name(f"rejection-{rejection}.json")
    temporary = tempfile.TemporaryDirectory(
        prefix="codex-connection-e2e-", ignore_cleanup_errors=True
    )
    directory = Path(temporary.name)
    cert, key = certificate(directory)
    listen = socket.socket()
    listen.bind(("127.0.0.1", 0))
    port = listen.getsockname()[1]
    listen.close()
    origin = f"https://127.0.0.1:{port}"
    os.environ["AUTH_BOOTSTRAP_ADMIN_PASSWORD"] = "admin"
    app = TestAppFactory().create(
        overrides={
            "runtime": {
                "web": {
                    "cors": {
                        "allow_origins": ["http://testserver", origin]
                        + (["http://127.0.0.1:3329"] if "--browser-task" in sys.argv else [])
                    }
                },
                **(
                    {"stream": {"detail": {"allowed_origins": ["http://127.0.0.1:3329"]}}}
                    if "--browser-task" in sys.argv
                    else {}
                ),
                "codex_control": {
                    "max_connected_agents": 4,
                    **candidate.get("server", {}),
                },
            }
        }
    )
    boundary = FaultBoundary(app)
    server = uvicorn.Server(
        uvicorn.Config(
            boundary,
            host="127.0.0.1",
            port=port,
            ssl_certfile=str(cert),
            ssl_keyfile=str(key),
            access_log=False,
            log_level="warning",
            ws="wsproto",
        )
    )
    server_task = asyncio.create_task(server.serve())
    channel = None
    run_task = None
    journal = None
    resource = None
    proxy = None
    proxy_environment = {}
    try:
        await until(lambda: server.started, task=server_task)
        if "--caddy-reload" in sys.argv:
            from scripts.codex.acceptance.caddy_reload import run_caddy_reload

            await run_caddy_reload(
                binary=ROOT / "test-results/connection-hardening/caddy/caddy.exe",
                directory=directory,
                report=report,
            )
            report["passed"] = True
            return
        if "--health-isolation" in sys.argv:
            from scripts.codex.acceptance.health_isolation import run_health_isolation

            await run_health_isolation(app, origin=origin, certificate=cert, report=report)
            report["passed"] = True
            return
        proxy_url = None
        if proxy_kind is not None:
            from scripts.codex.acceptance.connect_proxy import AcceptanceConnectProxy

            proxy = AcceptanceConnectProxy(port)
            proxy_url = await proxy.start(
                certificate=cert if proxy_kind == "https" else None, key=key
            )
            if proxy_kind == "system":
                for name, value in {
                    "HTTPS_PROXY": proxy_url,
                    "https_proxy": proxy_url,
                    "NO_PROXY": "nonexistent.invalid",
                    "no_proxy": "nonexistent.invalid",
                }.items():
                    proxy_environment[name] = os.environ.get(name)
                    os.environ[name] = value

        def enroll():
            with httpx.Client(
                base_url=origin, verify=str(cert), trust_env=False, timeout=30
            ) as browser:
                device = DeviceSupport.authorize_device(browser)
                token = DeviceSupport.issue_browser_access_token(browser)
                response = browser.put(
                    "/codex/active-host",
                    json={"host_id": str(device.host_id), "expected_version": 0},
                    headers={"Authorization": f"Bearer {token}"},
                )
                response.raise_for_status()
                return device

        device = await asyncio.to_thread(enroll)
        keyroot = directory / "keys"
        keyroot.mkdir()
        private = device.private_key.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        (keyroot / f"{device.key_id}.dpapi").write_bytes(WindowsCurrentUserDpapi().protect(private))
        workspace = directory / "workspace"
        workspace.mkdir()
        settings = CodexHostAgentSettings.model_validate(
            {
                "agent": {
                    "host_id": device.host_id,
                    "key_id": device.key_id,
                    "display_name": "连接稳定性验收",
                    "deployment_profile": "development",
                    "control_plane_url": origin.replace("https:", "wss:")
                    + "/internal/codex-agents/connect",
                    "control_plane_api_url": origin,
                    "state_database": directory / "state.sqlite",
                    "ca_certificate_path": cert,
                    "network_mode": "system"
                    if proxy_kind == "system"
                    else "explicit"
                    if proxy_url
                    else "direct",
                    "proxy_url": proxy_url if proxy_kind != "system" else None,
                },
                "protocol": {
                    "agent_schema_version": "2.0",
                    "agent_version": "0.1.38",
                    "expected_codex_version": "0.145.0",
                    "app_server_schema_digest": "86501505d7a626582cd7ded6eee36ab6bbaae30fd5d5c1021c0330e3f99d8109",
                },
                "workspaces": [
                    {
                        "key": "acceptance",
                        "display_name": "Acceptance",
                        "root": workspace,
                        "allow_write": True,
                    }
                ],
            }
        )
        settings = settings.model_copy(
            update={
                "agent": settings.agent.model_copy(
                    update={
                        "codex_binary": next(
                            (
                                arg.split("=", 1)[1]
                                for arg in sys.argv
                                if arg.startswith("--codex-bin=")
                            ),
                            "codex",
                        )
                    }
                )
            }
        )
        if "--runtime-recovery" in sys.argv:
            settings = settings.model_copy(
                update={
                    "agent": settings.agent.model_copy(
                        update={"codex_binary": str(directory / "recovering-codex.cmd")}
                    )
                }
            )
        if any(flag in sys.argv for flag in ("--binary", "--scheduler", "--pause-only")):
            await binary_acceptance(directory, settings, app, boundary, report)
            report["passed"] = True
            return
        if rejection == "tls":
            untrusted = directory / "untrusted"
            untrusted.mkdir()
            wrong_ca, _ = certificate(untrusted)
            settings = settings.model_copy(
                update={
                    "agent": settings.agent.model_copy(update={"ca_certificate_path": wrong_ca})
                }
            )
        # 项目设置owner读取同一正式配置；本验收不修改用户工作区或登录身份。
        import rtoml

        (directory / "agent.toml").write_text(
            rtoml.dumps(json.loads(settings.model_dump_json(exclude_none=True))), encoding="utf-8"
        )
        if candidate:
            settings = settings.model_copy(
                update={
                    "agent": type(settings.agent).model_validate(
                        {
                            **settings.agent.model_dump(),
                            **candidate.get("agent", {}),
                        }
                    )
                }
            )
        network = AgentNetworkPolicy(settings.agent)
        assert set(ssl.create_default_context().get_ca_certs(binary_form=True)).issubset(
            set(network.tls_context.get_ca_certs(binary_form=True))
        ), "Additional CA replaced system trust roots"
        resource = SharedAsyncHttpClient(
            AsyncHttpClientDetail(
                timeout_seconds=15, max_connections=4, max_keepalive_connections=2
            ),
            tls_context=network.tls_context,
            proxy=network.http_proxy_for(origin),
            trust_env=False,
        )
        journal = AgentCommandJournal(settings.agent.state_database)
        channel = AgentControlChannel(
            settings=settings,
            network_policy=network,
            secret_store=WindowsAgentSecretStore(),
            connection_ticket_provider=AgentConnectionTicketProvider(
                client=resource.get_client(),
                control_plane_api_url=origin,
                key_store=WindowsDpapiDeviceKeyStore(root=keyroot),
            ),
            workspace_registry=AgentWorkspaceRegistry(
                [item.to_definition() for item in settings.workspaces]
            ),
            journal=journal,
            logger=logging.getLogger("acceptance"),
            config_path=directory / "agent.toml",
        )
        if "--runtime-recovery" in sys.argv:
            boundary.consume_next_ticket = False
            run_task = asyncio.create_task(channel.run())
            await until(lambda: channel._hello_ack_event.is_set(), task=run_task)
            assert not channel._connection_ready and channel._local_issue == "cli_not_found"
            runtime = app.state.container.resource_mount.get_codex_control_runtime()
            lease = await runtime.connection_registry.read(device.host_id)
            assert not lease.allowed_commands
            assert channel._supervisor.current_handle is None
            import shutil

            actual = shutil.which("codex")
            Path(settings.agent.codex_binary).write_text(
                '@echo off\ncall "' + actual + '" %*\n', encoding="utf-8"
            )
            await until(lambda: channel._connection_ready, timeout=120, task=run_task)
            assert channel._supervisor.handle.profile is not None
            ready_instance = channel._supervisor.handle.instance_id
            Path(settings.agent.codex_binary).write_text(
                '@echo off\nif "%1"=="--version" (echo codex-cli 9.9.9 & exit /b 0)\ncall "'
                + actual
                + '" %*\n',
                encoding="utf-8",
            )
            await until(
                lambda: (
                    channel._local_issue == "cli_version_unverified"
                    and channel._hello_ack_event.is_set()
                ),
                timeout=90,
                task=run_task,
            )
            assert not channel._connection_ready
            assert channel._supervisor.handle.instance_id != ready_instance
            lease = await runtime.connection_registry.read(device.host_id)
            assert not lease.allowed_commands
            epoch = channel._connection_epoch
            await asyncio.sleep(settings.agent.heartbeat_seconds + 1)
            assert channel._connection_epoch == epoch
            Path(settings.agent.codex_binary).write_text(
                '@echo off\ncall "' + actual + '" %*\n', encoding="utf-8"
            )
            await until(lambda: channel._connection_ready, timeout=90, task=run_task)
            report["scenarios"].append(
                {
                    "name": "idle CLI identity change reselects profile; unknown version retains stable management; known version automatically recovers",
                    "passed": True,
                }
            )
            report["scenarios"].append(
                {
                    "name": "missing CLI retains authenticated management and automatically recovers same device",
                    "passed": True,
                }
            )
            report["passed"] = True
            return
        boundary.failures = {
            "/internal/codex-agents/device-challenges": [520],
            "/internal/codex-agents/connection-tickets": [522],
            "/internal/codex-agents/connect": [520],
        }
        if rejection is not None:
            boundary.consume_next_ticket = False
            boundary.failures = (
                {}
                if rejection == "tls"
                else {"/internal/codex-agents/device-challenges": [int(rejection)]}
            )
        if "--approval-matrix" in sys.argv or proxy is not None:
            boundary.failures = {}
            boundary.consume_next_ticket = False
        run_task = asyncio.create_task(channel.run())
        if rejection is not None:
            await until(lambda: channel._connection_state == "blocked", task=run_task)
            expected = (
                "tls_validation_failed"
                if rejection == "tls"
                else "gateway_policy_denied"
                if rejection == "403"
                else "origin_tls_failed"
            )
            assert channel._connection_reason == expected, channel._connection_reason
            requests = boundary.auth_requests
            await asyncio.sleep(2)
            assert boundary.auth_requests == requests and not run_task.done()
            assert (keyroot / f"{device.key_id}.dpapi").is_file()
            report["scenarios"].append(
                {
                    "name": f"actual {rejection} blocks without hot retry or deleting key",
                    "passed": True,
                    "reason": expected,
                }
            )
            report["passed"] = True
            return
        await until(lambda: channel._connection_ready, timeout=120, task=run_task)
        runtime = app.state.container.resource_mount.get_codex_control_runtime()
        lease = await runtime.connection_registry.read(device.host_id)
        await until(
            lambda: lease.sender._confirmed_generation == channel._execution.generation,
            task=run_task,
        )
        first = channel._supervisor.handle
        if "--browser-task" in sys.argv:
            from scripts.codex.acceptance.browser_task import run_browser_task

            await run_browser_task(
                channel,
                origin=origin,
                certificate=cert,
                report=report,
                acceptance_report=output,
                timeout_seconds=int(
                    next(
                        (
                            arg.split("=", 1)[1]
                            for arg in sys.argv
                            if arg.startswith("--browser-timeout-seconds=")
                        ),
                        "720",
                    )
                ),
            )
            report["passed"] = True
            return
        if "--history-window" in sys.argv:
            from scripts.codex.acceptance.history_window import run_history_window

            await run_history_window(
                channel, origin=origin, certificate=cert, run_task=run_task, report=report
            )
            report["passed"] = True
            return
        if candidate and not any(arg.startswith("--soak-seconds=") for arg in sys.argv):
            from scripts.codex.autotuner.connection.scenarios import run_scenarios

            await run_scenarios(
                channel,
                runtime=runtime,
                run_task=run_task,
                proxy=proxy,
                boundary=boundary,
                report=report,
                candidate=candidate,
            )
            report["passed"] = all(item["passed"] for item in report["scenarios"])
            return
        soak_seconds = next(
            (int(arg.split("=", 1)[1]) for arg in sys.argv if arg.startswith("--soak-seconds=")),
            None,
        )
        if soak_seconds is not None:
            from scripts.codex.acceptance.connection_soak import run_connection_soak

            await run_connection_soak(
                channel,
                runtime=runtime,
                run_task=run_task,
                report=report,
                output=output,
                seconds=soak_seconds,
            )
            report["passed"] = True
            return
        if proxy is not None:
            assert boundary.websocket_peers[-1] in proxy.upstream_peers
            assert boundary.auth_peers[-1] in proxy.upstream_peers
            previous_tickets = len(boundary.tickets)
            proxy.interrupt_tunnels()
            await until(lambda: not channel._connection_ready, task=run_task)
            await until(
                lambda: channel._connection_ready and len(boundary.tickets) > previous_tickets,
                task=run_task,
            )
            assert channel._supervisor.handle.instance_id == first.instance_id
            assert boundary.websocket_peers[-1] in proxy.upstream_peers
            assert boundary.auth_peers[-1] in proxy.upstream_peers
            assert boundary.ticket_reuse == 0
            report["scenarios"].append(
                {
                    "name": f"{proxy_kind} CONNECT proxy: real HTTP and WSS, custom CA, tunnel interruption and fresh-ticket recovery",
                    "passed": True,
                    "tunnels": proxy.connections,
                }
            )
            report["passed"] = True
            return
        if "--approval-matrix" in sys.argv:
            from scripts.codex.acceptance.approval_matrix import run_approval_matrix

            await run_approval_matrix(
                channel,
                actor=runtime.actor_registry.get(device.host_id),
                journal=journal,
                origin=origin,
                certificate=cert,
                workspace=workspace,
                report=report,
                previous_report=json.loads(output.read_text(encoding="utf-8"))
                if "--approval-resume" in sys.argv and output.is_file()
                else None,
            )
            report["passed"] = True
            return
        report["scenarios"].append(
            {
                "name": "520/522 challenge-ticket-upgrade recovery",
                "passed": True,
                "faults": boundary.injected.copy(),
                "pid": first.process.pid,
                "instance": first.instance_id,
            }
        )
        assert any(item.get("reason") == "ticket_expired" for item in boundary.injected)
        report["scenarios"].append(
            {"name": "consumed connection ticket renews without re-enrollment", "passed": True}
        )
        if "--mutation-only" in sys.argv:
            effective = await channel._project_execution.resolve("acceptance", first.client)
            params = {"workspace_key": "acceptance"}
            op = uuid4()
            command = CodexAgentCommand(
                command_id=uuid4(),
                operation_id=op,
                host_id=device.host_id,
                command_type="thread.start",
                params=params,
                sandbox_mode=effective.sandbox_mode,
                approval_policy=effective.approval_policy,
                request_digest=calculate_agent_request_digest(
                    "thread.start",
                    params,
                    sandbox_mode=effective.sandbox_mode.value,
                    approval_policy=effective.approval_policy.value,
                ),
                deadline=datetime.now(UTC) + timedelta(seconds=90),
                execution_generation=channel._execution.generation,
            )
            original_request = first.client.request
            calls = 0

            async def count_mutation(method, params, **kwargs):
                nonlocal calls
                if kwargs.get("operation_id") == str(op) and method == "thread/start":
                    calls += 1
                return await original_request(method, params, **kwargs)

            first.client.request = count_mutation
            actor = runtime.actor_registry.get(device.host_id)
            result = await actor.dispatch_and_wait_result(
                command, ack_timeout_seconds=10, result_timeout_seconds=40
            )
            assert result.outcome == "completed", result
            repeated = await actor.dispatch_and_wait_result(
                command, ack_timeout_seconds=10, result_timeout_seconds=10
            )
            assert repeated.outcome == "completed" and calls == 1
            record = journal.read(str(command.command_id))
            assert record.result_summary.upstream_thread_id
            thread_id = record.result_summary.upstream_thread_id
            await original_request("thread/delete", {"threadId": thread_id}, timeout_seconds=15)
            first.client.request = original_request
            report["scenarios"].append(
                {
                    "name": "real thread.start executes once; duplicate ID replays; test thread deleted",
                    "passed": True,
                    "mutation_count": calls,
                }
            )
            report["passed"] = True
            return
        # 实际App Server读请求延迟20秒：超过heartbeat周期，但不能阻塞续租。
        actor = runtime.actor_registry.get(device.host_id)
        op = uuid4()
        params = {"workspace_key": "acceptance", "limit": 1}
        command = CodexAgentCommand(
            command_id=uuid4(),
            operation_id=op,
            host_id=device.host_id,
            command_type="thread.list",
            params=params,
            request_digest=calculate_agent_request_digest("thread.list", params),
            deadline=datetime.now(UTC) + timedelta(seconds=90),
            execution_generation=channel._execution.generation,
        )
        original_request = first.client.request
        calls = 0

        async def slow_request(method, params, **kwargs):
            nonlocal calls
            result = await original_request(method, params, **kwargs)
            if kwargs.get("operation_id") == str(op):
                calls += 1
                await asyncio.sleep(20)
            return result

        first.client.request = slow_request
        lease_deadline = channel._execution.deadline
        result = await actor.dispatch_and_wait_result(
            command, ack_timeout_seconds=10, result_timeout_seconds=40
        )
        assert result.outcome == "completed", result
        assert channel._execution.deadline > lease_deadline
        repeated = await actor.dispatch_and_wait_result(
            command, ack_timeout_seconds=10, result_timeout_seconds=10
        )
        assert repeated.outcome == "completed" and calls == 1
        first.client.request = original_request
        report["scenarios"].append(
            {
                "name": "slow real RPC keeps lease live; duplicate command replays journal",
                "passed": True,
                "upstream_calls": calls,
            }
        )
        # 在上游已答复但本地命令尚未收束时断开socket；命令worker继续持久化结果。
        op = uuid4()
        command = command.model_copy(
            update={
                "command_id": uuid4(),
                "operation_id": op,
                "deadline": datetime.now(UTC) + timedelta(seconds=90),
            }
        )
        upstream_done = asyncio.Event()
        calls = 0

        async def delayed_result(method, params, **kwargs):
            nonlocal calls
            result = await original_request(method, params, **kwargs)
            if kwargs.get("operation_id") == str(op):
                calls += 1
                upstream_done.set()
                await asyncio.sleep(2)
            return result

        first.client.request = delayed_result
        delivery = asyncio.create_task(
            actor.dispatch_and_wait_result(
                command, ack_timeout_seconds=10, result_timeout_seconds=5
            )
        )
        await asyncio.wait_for(upstream_done.wait(), 15)
        epoch = channel._connection_epoch
        lease = await runtime.connection_registry.read(device.host_id)
        lease.close(1012, "acceptance_result_disconnect")
        try:
            await delivery
        except (TimeoutError, CodexHostOfflineError):
            pass
        await until(
            lambda: channel._connection_ready and channel._connection_epoch != epoch, task=run_task
        )
        await until(
            lambda: (
                (r := journal.read(str(command.command_id))) is not None
                and r.state.value not in ("received", "executing", "accepted")
            ),
            timeout=10,
            task=run_task,
        )
        record = journal.read(str(command.command_id))
        assert record is not None and record.state.value == "completed", str(record)
        lease = await runtime.connection_registry.read(device.host_id)
        await until(
            lambda: lease.sender._confirmed_generation == channel._execution.generation,
            task=run_task,
        )
        result = await actor.dispatch_and_wait_result(
            command, ack_timeout_seconds=10, result_timeout_seconds=10
        )
        assert result.outcome == "completed" and calls == 1
        first.client.request = original_request
        report["scenarios"].append(
            {
                "name": "inflight result survives disconnect and original ID never reruns RPC",
                "passed": True,
                "upstream_calls": calls,
            }
        )
        # 服务端真实关闭信号1012贯穿route/session/Agent；短断线不得重建执行进程。
        epoch = channel._connection_epoch
        lease = await runtime.connection_registry.read(device.host_id)
        lease.close(1012, "acceptance_restart")
        await until(
            lambda: channel._connection_ready and channel._connection_epoch != epoch, task=run_task
        )
        assert channel._supervisor.handle.instance_id == first.instance_id
        report["scenarios"].append(
            {
                "name": "negotiated short disconnect retains process",
                "passed": True,
                "pid": first.process.pid,
                "epoch_before": epoch,
                "epoch_after": channel._connection_epoch,
            }
        )
        # 超过现有35秒授权窗口，不调大超时；故障入口持续522。
        boundary.failures["/internal/codex-agents/device-challenges"] = [522] * 20
        lease = await runtime.connection_registry.read(device.host_id)
        lease.close(1012, "acceptance_long_partition")
        await until(lambda: first.process.returncode is not None, timeout=45, task=run_task)
        assert not psutil.pid_exists(first.process.pid)
        report["scenarios"].append(
            {"name": "lease expiry confirms process tree stopped", "passed": True}
        )
        boundary.failures.clear()
        await until(
            lambda: (
                channel._connection_ready
                and channel._supervisor.handle.instance_id != first.instance_id
            ),
            task=run_task,
        )
        report["scenarios"].append(
            {"name": "long outage recovers without enrollment", "passed": True}
        )
        # 当前连接没有连续性协商时恢复原保守停止语义。
        runtime.settings = runtime.settings.model_copy(
            update={"agent_lease_continuity_enabled": False}
        )
        epoch = channel._connection_epoch
        lease = await runtime.connection_registry.read(device.host_id)
        lease.close(1012, "acceptance_rollback")
        await until(
            lambda: (
                channel._connection_ready
                and channel._connection_epoch != epoch
                and not channel._continuity
            ),
            task=run_task,
        )
        fallback = channel._supervisor.handle
        epoch = channel._connection_epoch
        lease = await runtime.connection_registry.read(device.host_id)
        lease.close(1012, "acceptance_legacy")
        await until(
            lambda: channel._connection_ready and channel._connection_epoch != epoch, task=run_task
        )
        assert channel._supervisor.handle.instance_id != fallback.instance_id
        report["scenarios"].append(
            {"name": "unnegotiated reconnect stops old execution", "passed": True}
        )
        # 原通道停止回执后才允许解除账号级draining，不以45秒计时冒充停止。
        lease = await runtime.connection_registry.read(device.host_id)
        await runtime.connection_registry.revoke(device.host_id)
        await until(lambda: channel._connection_state == "blocked", task=run_task)
        state = await runtime.active_host.read("user-admin")
        assert state.draining_host_id is None and state.active_host_id is None
        assert run_task is not None and not run_task.done()
        assert (keyroot / f"{device.key_id}.dpapi").is_file()
        report["scenarios"].append(
            {"name": "revocation confirms stop then blocks without deleting key", "passed": True}
        )
        assert boundary.ticket_reuse == 0
        report["ticket_reuse"] = boundary.ticket_reuse
        report["passed"] = True
    except BaseException as exc:
        report["passed"] = False
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if channel is not None:
            channel.request_shutdown()
        if run_task is not None:
            try:
                done, _ = await asyncio.wait((run_task,), timeout=12)
                if not done:
                    report["shutdown_pending"] = [
                        {
                            "task": task.get_name(),
                            "stack": [
                                f"{frame.f_code.co_filename}:{frame.f_lineno}:{frame.f_code.co_name}"
                                for frame in task.get_stack()
                            ],
                        }
                        for task in asyncio.all_tasks()
                        if task is not asyncio.current_task()
                    ]
                await asyncio.wait_for(run_task, 15)
            except BaseException as exc:
                report["shutdown_error"] = type(exc).__name__
                logging.exception("Agent shutdown failed during acceptance")
                report["passed"] = False
        if journal is not None:
            journal.close()
        if resource is not None:
            await resource.close()
        if proxy is not None:
            await proxy.close()
        for name, value in proxy_environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        server.should_exit = True
        await asyncio.wait_for(server_task, 30)
        report["completed_at"] = datetime.now(UTC).isoformat()
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.cleanup()
        print(json.dumps(report, ensure_ascii=False))
        if "shutdown_error" in report:
            raise RuntimeError("Agent acceptance failed during shutdown")


if __name__ == "__main__":
    asyncio.run(main())
