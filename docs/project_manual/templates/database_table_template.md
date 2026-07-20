# 表名

## 模板元信息
- 文档目的：提供新增同类文档时的稳定结构。
- 适用读者：后端开发者、测试维护者、运维部署人员、安全审查人员。
- 最后更新范围：仅覆盖 `/docs/project_manual/templates` 中的写作模板。
- 关联源码：模板不绑定单一源码文件，使用时必须替换为真实路径、类名、函数名、配置项和测试文件。
- 使用约束：只记录 ORM、Alembic、repository、配置和测试可确认的事实，不保留占位符，不虚构表结构或业务含义。

## 1. 表用途

## 2. ORM 模型

记录 `src/infrastructure/persistence/orm_model` 中的模型、主键、外键、mixin 和命名约定。

## 3. Alembic 迁移

记录 `src/infrastructure/persistence/alembic/versions` 中创建或修改该表的版本链。

## 4. 字段说明

| 字段 | 类型 | 约束 | 说明 |
| ---- | ---- | ---- | ---- |
|      |      |      |      |

## 5. 索引与唯一约束

## 6. Repository

记录对应 `src/infrastructure/persistence/repository_impl` 实现和 `src/core/persistence_contract` 契约。

## 7. 读写场景

记录哪些 usecase、runtime 或后台 API 会读写该表。

## 8. 数据一致性注意事项

说明 UnitOfWork 事务边界、幂等/去重约束、软删除或状态流转规则。

## 9. 测试覆盖

| 测试类型 | 测试文件 | 覆盖内容 |
| -------- | -------- | -------- |
|          |          |          |

## 相关文档
- [项目文档总览](../README.md)
