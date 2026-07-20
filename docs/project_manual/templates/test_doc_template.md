# 测试主题

## 模板元信息
- 文档目的：提供新增同类文档时的稳定结构。
- 适用读者：后端开发者、测试维护者、运维部署人员、安全审查人员。
- 最后更新范围：仅覆盖 `/docs/project_manual/templates` 中的写作模板。
- 关联源码：模板不绑定单一源码文件，使用时必须替换为真实路径、类名、函数名、配置项和测试文件。
- 使用约束：只记录当前 `test`、`pyproject.toml` 和测试 support 可确认的事实，不虚构覆盖率或测试结果。

## 1. 测试目标

## 2. 测试层级

unit / contract / interface / integration / boundary / exception / initialization / path / convention_usage / class_inheritance

## 3. 测试文件

| 测试类型 | 测试文件 | 覆盖对象 |
| -------- | -------- | -------- |
|          |          |          |

## 4. 关键断言

## 5. 依赖资源

数据库、Redis、RabbitMQ、环境变量、`test/conftest.py` fixture、`src/infrastructure/testing` support 等；外部组件不可用时测试失败，阶段证据说明 `blocked` 前置条件。

## 6. 如何新增类似测试

说明应放入哪个 `test/*_test` 目录、需要哪些 fake/test support、如何运行相关 pytest，以及同步哪些项目手册文档。

## 相关文档
- [项目文档总览](../README.md)
