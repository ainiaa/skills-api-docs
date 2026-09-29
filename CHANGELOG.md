# 变更日志

本项目的重要变更记录在此文件中，格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [0.3.0] - 2026-09-29

- 修复官方引擎选择顺序：显式 CLI 路径优先，其次使用本 Skill 组安装的引擎，最后查找系统 PATH；Linux 无桌面环境会使用带 Xvfb 的 draw.io 包装器。
- CI 改为从空用户目录通过正式安装脚本准备四个渲染引擎，并运行官方引擎验收；GitHub Ubuntu 运行器的 Mermaid Chromium 沙箱限制仅在 CI 包装器中处理。
- 安装器默认为 Codex 和 Claude Code 同时链接两个 Skill，并自动补齐缺失的 Mermaid、PlantUML、draw.io、Archify 引擎；可用 `--host`、重复 `--engine` 或 `--no-engines` 限定范围。显式跳过引擎会保留偏好，Skill 后续不擅自安装；已安装的引擎可复用，卸载 Skill 不删除共享引擎。Python 最低版本提升为 3.11，生成与渲染入口会进行版本检查。
- Skill 名称统一为 `understand-docs` 与 `understand-arch`；安装器迁移本仓库拥有的 `api-savior-docs`、`understand-api-docs`、`understand-api-arch` 旧链接，并保留无关同名路径。
- 安装方式改为 Skill 组：根目录 `install.sh` 一次安装、诊断和卸载 `understand-docs` 与 `understand-arch` 两个入口；兼容旧版只安装一个入口的环境，并在写入前检查两个目标路径，避免冲突造成部分安装。`install-arch.sh` 保留为单独管理入口。
- 修复架构候选覆盖的假通过：识别多行 Spring 映射，候选按源文件区分并要求被映射图元引用全部命中行；畸形候选决定改为结构化校验错误。PlantUML 原生通道补齐 `!includesub` 与 `!include file!编号/ID` 的选中内容核验和本地文件打包。
- `understand-arch` 增加源码候选清单与严格架构交付：候选事实须逐项映射到总览、细节关系或说明排除原因，清单在校验时重新扫描源码；`deliver` 一次渲染所有细节图并检查 draw.io 卡片几何，旧自报省略清单改标 `declared_only`。候选扫描补识别多行 `@HttpApi*Mapping` 自定义入口。PlantUML 本地 include 纳入证据覆盖和产物，未能清点的外部 include 标为 `partial`。
- `understand-arch` 强化来源与覆盖校验：IR v2 的 `EXTRACTED` 名称／关系标签须逐字出现在引用源码；原生证据清单 v2 按 Mermaid/PlantUML 行、draw.io 单元和 Archify typed 项逐项检查覆盖，旧清单保持可读但标记覆盖未检查；架构总览可声明省略事实并校验配套细节 IR。
- C4 容器图与组件图在 draw.io、PlantUML、Mermaid 中显式绘制系统／容器范围；draw.io 总览的跨层线路避开已占用通道，细节图模块边界不再遮住副标题。以 IES 项目补充 Redis 依赖细节图并验证总览覆盖记录。
- `understand-arch` 新增 draw.io `architecture-landscape` 总览视图：默认把源码支持的入口、模块边界、业务服务、数据设施和外部依赖分层；节点角色使用不同形状与色彩，主／辅助／依赖链路以颜色和线型区分，并以编号关系索引保持长标签可读。单图超出 12 个节点或 12 条关系、标签超长时拒绝交付，要求拆成概览与聚焦视图；以 FA 模块无参考图案例完成真实导出与审图。
- `understand-arch` 增加面向 Mermaid、PlantUML、draw.io 和 Archify 官方原生语法的源码绘图流程：先选图型、核对代码、编写可编辑原生文件，再交给对应官方引擎验收与按需导出。新增逐条关联图中文字、来源状态和当前源码行的证据清单；无效引用在写入成品前拒绝，回执区分锚点验证与尚未证明的业务解释。
- 对照四个引擎的官方图型目录新增[能力审计](docs/RENDERER_CAPABILITY_AUDIT.md)；增加 `render_native_diagram.py`，可直接用官方 CLI 验证并导出 Mermaid、PlantUML、draw.io 原生文件及 Archify 五种 typed JSON 模式。回执明确区分官方验收与未检查的源码证据，CI 增加各引擎原生图测试。
- draw.io 新增 IR v2 UML 时序图适配：可编辑生命线、按序调用、异步与返回消息，以及自调用；通过官方 draw.io 导出和 FA 真实代码时序图的图片审查。修正了此前“draw.io 不支持时序图”的错误表述；激活条和组合片段仍未实现。
- `understand-arch` 新增可核对的绘图规范、分型 IR v2 与默认简短请求流程：按 C4、UML 时序、BPMN 可视子集、Crow's Foot ERD 的语义分别校验；不支持的图型/引擎组合明确拒绝，旧 IR v1 保持兼容。
- 已有 CodeGraph 索引且状态新鲜时，`context` 读取结构化类、路由和通过 `--focus` 指定的调用关系；导出回执区分官方引擎检查与仍需人工完成的视觉审查。C4 draw.io 改用分层布局、中文图例及定向连线；此前 FA 图片虽成功导出，但视觉质量未达用户要求，现由总览密度门槛和实际审图补上验收。
- 新增独立的 `understand-arch` Skill 与 CLI：无数量截断的源码上下文、逐条源码行证据校验，以及 Mermaid、PlantUML、draw.io、Archify schema-v1 输出；调用入口与 API 文档 Skill 分离。
- 架构 IR 与 API Document IR 独立，保留来源状态 `EXTRACTED`／`INFERRED`／`AMBIGUOUS`；校验失败时不写新图。
- Archify 接入官方 v2.16.0 `deliver --quality showcase` 验收：生成 HTML 与校验回执，失败时返回非零并清理旧 HTML；修复跨格式节点 ID 冲突、表格布局冲突及畸形 IR 导致的渲染异常。
- Mermaid、PlantUML、draw.io 接入官方 CLI 验收：`render --format` 按需交付选中的原生格式，只有显式指定 `--svg-for <格式>` 才交付该格式的 SVG；返回 `rendererChecks` 状态，显式要求的引擎缺失或验收失败时返回非零并清理旧成品。CI 固定三套工具版本，使用真实引擎验证生成结果。
- 架构图按 `--export-for 引擎:格式` 显式导出：Mermaid、PlantUML 为 SVG/PNG/PDF，draw.io 为 SVG/PNG/JPG/PDF，Archify 通过官方 HTML 查看器导出 SVG/PNG/JPG/WebP/WebM 并通过浏览器打印生成 PDF；验收成品并清理失败或过期的导出。`--svg-for` 保持兼容。

## [0.2.0] - 2026-09-27

- tree-sitter 回退引擎的语言覆盖扩展至 TypeScript（`.ts`/`.tsx`）、Go、PHP：主查询逐字 vendor 自各语法上游仓库的 tags.scm 并注明来源与版本，TypeScript 以补充查询覆盖上游签名导向查询缺失的具体类/函数/枚举声明；全部查询外置为 `scripts/queries/<语言>/` 下的文件。文档生成适配器仍为 Java 与 Python，新语言的符号已可被引擎定位。
- 引擎支持扩展至 Python/FastAPI：`--endpoint` 定位路由函数并输出提示，未解析类型自动补包根（按 `__init__.py` 链推导），`--changed` 覆盖 Python 的传递引用；typing 名称（`Any`/`Union`/`Literal`）不再误报为未解析。
- 发现协议新增 `locate_many` 批量定位：`--changed` 先做纯 IR 可达性遍历，再一次批量查询全部候选类型；codegraph 后端以线程池并行执行逐名查询，无关 schema 依旧零查询。
- tree-sitter 回退引擎新增按文件的 mtime+size 跨运行缓存（存放系统临时目录，查询文本变化自动失效，读写全部 fail-open），大仓库重复运行的解析成本大幅下降。
- tree-sitter 符号提取对齐官方 tags.scm 规范：声明按 `@name` + `@definition.<kind>` 成对捕获、经 `matches()` 配对解析，行为不变，为后续直接引入各语法上游 tags.scm 文件扩展语言做准备。
## [0.1.0] - 2026-09-27

- 新增可选的代码发现引擎层：引擎只回答"文件与符号在哪"，字段、wire 名、枚举等语义仍由源码解析产生；无引擎时行为与旧版逐字节一致。
- 引擎按可用性自动回退：codegraph（仓库含 `.codegraph/` 且安装 CLI）→ tree-sitter（可选包 `tree-sitter`、`tree-sitter-python`、`tree-sitter-java`）→ 无引擎；`--no-codegraph` 显式关闭整个发现层。
- `--endpoint` 不再需要先传 `--controller`：按接口方法名定位 Controller 文件，缩小扫描范围；歧义或定位失败时自动回退全量扫描并沿用既有报错。
- 报出未解析 DTO 类型时自动反查类型定义、推导包根并重扫（最多 2 轮），stderr 以 `[codegraph]`/`[tree-sitter]` 前缀说明补了什么；带包名的类型按包名过滤定位结果，同名类不会补错根。
- 新增 `--changed <改动文件>`：只重新生成受改动影响的接口段落，覆盖 Controller 源文件本身与 DTO 的传递引用；schema 沿引用可达性惰性定位，无关类型不触发引擎查询；无受影响接口时不写任何文件。
- 修复 macOS 符号链接环境下 tree-sitter 回退路径未 resolve 导致 narrowed scan 静默失效的问题；`--no-codegraph` 的优先级高于测试钩子环境变量。
- 文档同步：SKILL.md 与 README 增补发现引擎章节、降级规则与可选依赖安装方式。

[Unreleased]: https://github.com/ainiaa/skills-api-docs/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/ainiaa/skills-api-docs/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/ainiaa/skills-api-docs/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/ainiaa/skills-api-docs/releases/tag/v0.1.0
