# PyInstaller one-folder specification for the signed per-user Agent bundle.
from pathlib import Path

project_root = Path(SPECPATH).parents[2]

a = Analysis(
    [str(project_root / "src" / "cli" / "run_codex_host_agent.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(project_root / "protocol"), "protocol"),
    ],
    hiddenimports=["cryptography.hazmat.bindings._rust"],
    excludes=["tkinter", "pytest", "nox"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="codex-remote-agent",
    console=True,
)
coll = COLLECT(exe, a.binaries, a.datas, name="codex-remote-agent")
