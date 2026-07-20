"""
应用主入口模块。
"""

from __future__ import annotations

from src.api.asgi_entry import create_app

app = create_app()
