"""仅供本机浏览器端到端验收的隔离应用；无共享数据库或生产凭据。"""

import os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
os.environ["AUTH_BOOTSTRAP_ADMIN_PASSWORD"] = "admin"
from src.api.testing.test_app_factory import TestAppFactory
import uvicorn

app = TestAppFactory().create(
    overrides={
        "runtime": {
            "web": {"cors": {"allow_origins": ["http://127.0.0.1:3329"]}},
            "stream": {"detail": {"allowed_origins": ["http://127.0.0.1:3329"]}},
        }
    }
)
uvicorn.run(app, host="127.0.0.1", port=3339, log_level="warning", access_log=False)
