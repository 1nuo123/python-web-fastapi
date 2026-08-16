# 已签名的当前用户 Agent one-file 构建规格。
import os
from pathlib import Path

project_root = Path(SPECPATH).parents[1]
version_file = os.environ["CODEX_AGENT_VERSION_FILE"]

a = Analysis(
    [str(project_root / "src" / "cli" / "run_codex_host_agent.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(project_root / "protocol"), "protocol"),
    ],
    hiddenimports=[
        "cryptography.hazmat.bindings._rust",
        "tkinter",
        "tkinter.filedialog",
        "tkinter.messagebox",
    ],
    excludes=["pytest", "nox"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="codex-remote-agent",
    console=False,
    version=version_file,
)
