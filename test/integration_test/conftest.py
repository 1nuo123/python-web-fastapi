"""集成测试目录约定。

PostgreSQL 会话级 ``integration_database`` 夹具由根目录 ``test/conftest.py``
唯一导出，避免同一测试会话重复注册资源夹具。
"""
