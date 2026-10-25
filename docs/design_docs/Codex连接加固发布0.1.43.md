# Codex 连接加固 0.1.43 发布交付

日期：2026-10-25。用户要求构建到 `E:/python_web_fastapi/codex-remote-agent-releases`，由用户手动发布。

## 产物

发布目录：`E:/python_web_fastapi/codex-remote-agent-releases/releases/0.1.43`。

该目录包含 MSI、internal-release.json、SHA256SUMS.json、build-evidence.json、source-files.sha256.json 和唯一操作说明 `发布操作.md`。Git 提交、GitHub 网页手动发布、等待前后端 CI、服务器更新及回滚依据都由这份说明管理，不在多份文档复制整套命令。

MSI SHA256：`72aacf1a08564c8dd7d518e9c7088287f8023233cb5beb068ff533877c2a5cdd`。

从 MSI 实际解出的 EXE SHA256：`49a1f25a127d65c04e19ab41ce3af72b055394ddbdff2c80ed9467078fb32af8`。

采用项目既有 internal 方式：Windows x64、per-user、生产域名 `https://nuotop.xyz`，未启用自动更新。包未作 Authenticode 签名，不能作为签名发行版描述。

## 版本与配置闭包

0.1.42 目录此前已有其他来源的发布包，因此本轮使用新版本0.1.43，不覆盖历史目录。构建入口仍为 `scripts/codex/build_internal_production_agent_installer.ps1`。

`config/runtime/codex_control_runtime/codex_control_runtime_base.toml` 与 production TOML 中的 release version、MSI摘要、下载/manifest URL、来源基线均与新清单对齐。保持 internal、source_dirty=true，minimum_security_version仍为0.1.31。没有擅自强制旧客户端升级。

本轮按“先构建、用户后提交”的要求生成，因此source_revision是构建时HEAD，source_dirty=true；逐文件输入摘要补充工作区来源。不要将manifest手工改为未来提交SHA并声称由干净提交重建。源码仍需用户提交推送；服务器单纯pull旧HEAD不会得到这些改动。

发布链接只有在用户手动创建 **v0.1.43** GitHub Release 并上传附件后才有效。向master提交MSI不等于发布Release。服务器应在附件可下载、两个main对应CI镜像构建成功后更新。

## 检查边界

MSI经WiX解包，EXE、bootstrap及三个生命周期脚本与构建payload逐字节相同；MSI版本、per-user身份、生产入口与无自动更新配置已核对。实际运行验收结果以release目录中的build-evidence.json为准。

未在用户电脑安装或升级生产Agent，未改计划任务；没有自动commit、push、发布Release或部署服务器。12小时证据仍是原轮次不可变记录；本轮版本资源和下载元数据调整不伪装成又跑过一次12小时。

## 服务器更新要点

继续复用现有 `deploy/production.sh update`（预检镜像、数据库备份、fast-forward、按digest部署），不在低内存生产主机上构建。当前Caddy单文件挂载需要一次受控重建才能保证Git更新的新文件生效；操作说明包含保留旧配置、校验、重建和最终状态检查。它会有短暂入口中断，应在无运行中任务时执行。

原环境检查报告记录的是升级前实况；“未生成安装包”这一缺口在本次构建完成后由本记录承接。生产依赖组合的完整验收及安装/升级实际验收仍不能由包解构和连接冒烟替代。
