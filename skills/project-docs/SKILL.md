---
name: project-docs
description: 项目文档 Skill 集合的统一入口；当用户点名 project-docs、安装或升级本集合，或要求根据仓库代码和需求资料选择、组合生成项目说明、接口文档与技术图时使用。
---

# Project Docs

根据读者、范围和交付物选择本集合的专用能力。先解析当前 Skill 的真实目录；下表链接均相对该目录。读取选中能力的 `SKILL.md` 后，遵循其取证、生成和验证要求。

用户要求更新本集合及依赖时，运行 `bash <真实Skill目录>/../../install.sh --update --host <宿主>`；根据当前实际宿主选 `codex`、`claude`、`zcode`、`dsh`、`gemini`、`grok`、`pi` 或 `opencode`，用户明确要求全部宿主时才用 `all`。只同步依赖时使用 `--update-deps`，仅更新 Skill 时加 `--no-engines`；诊断和卸载也使用同一个 `--host`。不要省略宿主参数后误用默认的 Codex、Claude Code 两端。三个子 Skill 随仓库更新，绘图 CLI 同步到集合锁定的版本，显式 CLI 覆盖由外部管理。更新保护本地改动，不自动切分支或重置；失败时报告具体阶段，不宣称全部更新成功。普通文档生成不先联网升级，也不升级用户的其他全局 Skill。

| 用户需要 | 读取的能力 | 交付物 |
|---|---|---|
| Spring MVC、Feign 或 FastAPI 接口文档 | [project-docs-api](../project-docs-api/SKILL.md) | API Markdown、Postman Collection、cURL 示例 |
| 架构图、流程图、泳道图、时序图、ERD，或处理 Mermaid、PlantUML、draw.io、Archify 图源 | [project-docs-diagram](../project-docs-diagram/SKILL.md) | 可编辑图源、按需导出文件及验证回执 |
| 项目介绍、功能说明、架构总览文档或开发者上手手册 | [project-docs-overview](../project-docs-overview/SKILL.md) | 按对应模板生成、带来源的 Markdown |

用户已明确交付物时直接选择，无需再询问入口名称。仅要求画图时读取绘图能力；“架构总览文档”由文档能力组织正文，并读取绘图能力完成必需的系统全景图和核心流程图。保留用户指定的图型、引擎和导出格式。

组合请求按交付物衔接。例如“介绍项目，附 draw.io 架构图和接口文档”使用文档能力组织正文、绘图能力交付图片与图源、接口能力生成独立接口产物，最后在正文中关联。复用已核对的源码范围与证据，仍执行每项交付物各自要求的检查；不能用一项通过代替其他项通过。

没有指定输出位置时遵循专用能力的默认位置；组合产物放在同一交付目录及子目录，用相对链接关联。交付时列出实际完成的文件、验证结果与未完成项。生成文档不授权修改业务代码、发布到飞书或提交到目标仓库。
