# Codex App Server 协议快照维护

## 添加版本

1. 固定并校验官方 Codex artifact，不使用动态 `latest`。
2. 执行 `uv run python -m scripts.codex.generate_app_server_schema --expected-version <version>`。
3. 生成器只允许写入全新版本目录；初始 `review_status` 必须为 `blocked`。
4. 审核官方 schema、method catalog、capability、许可证和产品 mapper 后，单独把状态改为 `approved`。
5. 运行 schema drift、兼容策略、codec、adapter 和真实 stdio 集成测试。

`0.145.0` 当前冻结值：JSON Schema bundle `86501505d7a626582cd7ded6eee36ab6bbaae30fd5d5c1021c0330e3f99d8109`，TypeScript bundle `125dea8051ad1d8ae9c9c527e30d1d6aada2965fd1e77771f7c18806c77a6724`。生产 Docker image 必须携带整个 `protocol/` 目录，不能只复制单个 digest。

## 审核差异

- 比较 `manifest.json`、combined schema 和产品实际使用方法，不手工修改官方生成的 JSON Schema 或 TypeScript。
- 未知 enum、额外字段、缺字段、方法方向变化和 payload 容量变化必须有明确 warning/block 策略。
- 新 digest 不得覆盖旧目录；需要新的精确版本目录与兼容矩阵记录。

## 弃用与回滚

- 弃用先改为 `deprecated`，只允许已评审的读取路径；mutation 不得因版本通配符继续放行。
- 紧急阻断改为 `blocked` 并停止 release matrix；回滚只切换到仍在仓库中的已审核 manifest 和对应 Codex artifact。
- 删除版本前必须确认受支持 Agent 使用率为零、保留审计证据并单独评审迁移。

## 许可证

官方生成物与 Codex artifact 的来源、版本、许可证和再分发条件记录在 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。发布包必须携带审核后的 notice，生成物不得被误标为本项目原创实现。
