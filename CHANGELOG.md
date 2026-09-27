# 变更日志

本项目的重要变更记录在此文件中，格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [0.1.0] - 2026-09-27

- 新增可选的代码发现引擎层：引擎只回答"文件与符号在哪"，字段、wire 名、枚举等语义仍由源码解析产生；无引擎时行为与旧版逐字节一致。
- 引擎按可用性自动回退：codegraph（仓库含 `.codegraph/` 且安装 CLI）→ tree-sitter（可选包 `tree-sitter`、`tree-sitter-python`、`tree-sitter-java`）→ 无引擎；`--no-codegraph` 显式关闭整个发现层。
- `--endpoint` 不再需要先传 `--controller`：按接口方法名定位 Controller 文件，缩小扫描范围；歧义或定位失败时自动回退全量扫描并沿用既有报错。
- 报出未解析 DTO 类型时自动反查类型定义、推导包根并重扫（最多 2 轮），stderr 以 `[codegraph]`/`[tree-sitter]` 前缀说明补了什么；带包名的类型按包名过滤定位结果，同名类不会补错根。
- 新增 `--changed <改动文件>`：只重新生成受改动影响的接口段落，覆盖 Controller 源文件本身与 DTO 的传递引用；schema 沿引用可达性惰性定位，无关类型不触发引擎查询；无受影响接口时不写任何文件。
- 修复 macOS 符号链接环境下 tree-sitter 回退路径未 resolve 导致 narrowed scan 静默失效的问题；`--no-codegraph` 的优先级高于测试钩子环境变量。
- 文档同步：SKILL.md 与 README 增补发现引擎章节、降级规则与可选依赖安装方式。

[Unreleased]: https://github.com/ainiaa/skills-api-docs/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ainiaa/skills-api-docs/releases/tag/v0.1.0
