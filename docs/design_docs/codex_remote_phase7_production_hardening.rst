Phase 7 生产硬化与隔离证据
================================

本文记录 Phase 7 已落地的可验证实现边界。未具备真实外部环境证据的项目保持为
“待验收”，不得以单元测试结果替代生产门。

Worktree 隔离
-------------

实现位于 ``src/core/worktree_contract``、``src/application/ports/git_worktree_port.py``
和 ``src/infrastructure/worktree/git_worktree_adapter.py``。适配器只通过 argv 调用
系统 Git，校验仓库根、受管目录、marker、锁和符号链接解析后的 containment。

清理策略
~~~~~~~~~

默认策略关闭。干净且到期的 worktree 才能由 ``prune`` 清理；未提交修改、目录占用、
Git 失败和 marker 不匹配均进入 ``pending_cleanup``，不会自动强删未知目录。容量和磁盘
使用率通过 ``GitWorktreeListResult`` 返回，协调器位于
``src/infrastructure/worktree/worktree_cleanup_reconciler.py``。

线程生命周期
~~~~~~~~~~~~

控制面只发送 ``workspace_key`` 与强类型 ``worktree_policy``，Agent 在 thread start
之前创建 worktree，并在 App Server 返回 thread 标识后绑定 marker。后续受支持的
thread/turn 命令按 thread 标识查找受管 worktree，绝不接受控制面绝对路径或 shell 命令。

生产硬化策略
-------------

``src/core/codex_contract/production_hardening_contract.py`` 定义公开注册滥用阈值、数据
留存和 SLO 的公共头与强类型扩展字段；``src/domain/codex/production_rollout_policy.py``
在错误预算或事件 gap 超限时返回暂停 rollout 的决定。指标不允许携带用户、主机、线程
等高基数标签。

灾备与公开注册门
-----------------

PostgreSQL 恢复后 Redis 被视为无状态：presence、challenge 和 ticket 全部失效，Agent
必须重新 challenge；不会从数据库恢复旧 presence。公开注册仍必须通过现有 fail-closed
限流器、安全事件和主体所有权校验。真实 ASN、CDN/TUF、clean Windows、备份恢复、外部
渗透和 canary 证据在对应环境执行后补写，不以本地替身冒充。

本地回归证据
------------

2026-08-08 仓库级验证完成：静态门禁通过，offline 为 ``925 passed, 1 deselected``，
regression 为 ``1076 passed``，合并覆盖率为 ``85.35500427715996%``。Docker Compose
重建后 app、PostgreSQL、Redis 和 RabbitMQ 均为 healthy，Alembic head 为
``202608081000``，容器内 ``cryptography`` 为 ``50.0.0``，并已携带冻结的
``protocol/`` 快照目录。

这些结果覆盖本地 worktree、owner boundary、secret/static gate、留存策略契约和 rollout
暂停策略，不替代 clean Windows、真实备份恢复、CDN/TUF 中断、容量 soak、外部渗透或
生产 canary 验收。

残余风险
--------

* 真实 Windows 文件占用、磁盘不足和 junction 攻击需要在 Windows runner 验证。
* 公开注册 ASN 信誉源、对象存储故障和完整灾备演练依赖部署环境，当前仓库未伪造通过证据。
* E2EE 仍需独立评审；AES-GCM outbox 仅提供落库机密性与完整性，不代表服务器不可读。
