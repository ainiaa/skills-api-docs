# Project Docs

面向 Codex、Claude Code、ZCode、DeepSeek Harness（DSH）、Gemini CLI、Grok Build、pi 和 OpenCode 的项目文档 Skill 集合。`project-docs` 是统一入口，根据需求选择或组合三个专用能力：`project-docs-api` 生成接口文档，`project-docs-diagram` 生成和校验技术图，`project-docs-overview` 生成项目介绍、功能说明与开发者上手手册。所有宿主共用同一份仓库与渲染引擎安装。

当前开发版本：[0.5.0](VERSION)（尚未发布）。改动记录见[变更日志](CHANGELOG.md)。

## 快速开始

1. 克隆仓库，一次安装统一入口、三个专用 Skill 与缺失的绘图引擎：

   ```bash
   git clone https://github.com/ainiaa/skills-api-docs.git
   cd skills-api-docs
   bash install.sh
   ```

2. 检查 Skill 入口和四个引擎，再重启或刷新宿主的 Skill 发现：

   ```bash
   bash install.sh --doctor
   ```

   以上默认管理 Codex、Claude Code。其他宿主在安装和诊断时均加相同的 `--host`，例如 `bash install.sh --host zcode` 和 `bash install.sh --doctor --host zcode`；全部八个宿主使用 `--host all`。完整目录与加载规范见下方[宿主支持](#宿主支持)。

3. 直接描述目标，或显式点名 Skill：

   ```text
   Codex：使用 $project-docs 介绍这个项目，附上系统架构图、核心流程图和接口文档。
   Codex：使用 $project-docs-api 为这个 Spring Controller 生成 API 文档。
   Codex：使用 $project-docs-diagram 根据这个项目的代码生成 draw.io 架构图，并导出 PNG。
   Codex：使用 $project-docs-overview 根据代码和现有需求资料写项目介绍及主要功能说明。
   Codex：使用 $project-docs-overview 为新开发者写项目上手手册。
   Claude Code：/project-docs 介绍这个项目，附上系统架构图和核心流程图。
   Claude Code：/project-docs-api 为这个 Spring Controller 生成 API 文档。
   Claude Code：/project-docs-diagram 根据这个项目的代码生成 draw.io 架构图，并导出 PNG。
   Claude Code：/project-docs-overview 为退款功能写现状、规则、端到端链路和风险说明。
   ```

生成文档和图时，只需向当前宿主提出需求；内部 Python 脚本由 Skill 按需调用，普通使用者不必运行它们。

### 选哪个 Skill

| 需求 | Skill | 主要交付物 |
|---|---|---|
| 统一选择入口，或组合交付说明文档、技术图和接口文档 | [`project-docs`](skills/project-docs/SKILL.md) | 按需求组合下列产物 |
| 从 Spring MVC、Feign 或 FastAPI 源码生成接口文档 | [`project-docs-api`](skills/project-docs-api/SKILL.md) | Markdown、Postman Collection、cURL 示例 |
| 根据仓库证据绘制架构、流程、时序、ERD 等技术图 | [`project-docs-diagram`](skills/project-docs-diagram/SKILL.md) | 可编辑图源、按需导出的图片或 PDF、验证回执 |
| 根据源码与需求资料介绍项目、评估架构、描述功能或引导新开发者 | [`project-docs-overview`](skills/project-docs-overview/SKILL.md) | 带来源的项目总览、架构总览、功能说明或上手手册 Markdown |

## 为什么会有它

Project Docs API 将 API Savior IDEA 插件的 RESTful 文档风格带到 Codex 和命令行，从真实路由、DTO 和枚举声明生成文档。Project Docs Diagram 让“根据代码画架构图”成为可检查的工作：先确定图型和范围，再关联源码证据、生成图源、调用实际渲染引擎，并检查成品。Project Docs Overview 将需求口径、实际实现和验证证据组织成面向读者的项目或功能叙述。

集合中的所有能力都会保留源码无法确定的部分，不把推断伪装成已验证事实。图源通过引擎验收，也仍需审阅业务解释和视觉效果。

## 能力与边界

| 能力 | 当前实现 |
|---|---|
| 接口文档输入 | Java Spring MVC Controller、Feign Client；Python FastAPI 路由 |
| 接口文档内容 | 请求和响应字段、JSON 示例、源码可解析的枚举；未解析类型会明确标出 |
| 项目、功能与上手说明 | 服务对象、功能地图、业务规则、端到端链路、现状与改动、验证场景和风险；上手手册另含环境、运行、测试与排障入口 |
| 架构总览文档 | 系统全景图、核心流程图、模块边界、通信、数据、可观测性、扩展性及有依据的五维评估；跨系统关系复杂时补系统上下文图 |
| 架构图生成 | 源码上下文、候选清单、分型 IR v2、覆盖决策、验证及交付；项目／模块总览默认使用 draw.io |
| 其他图型 | C4、UML 时序、BPMN 可视子集、ERD 等已实现 profile；其余官方图型可编写引擎原生文件并验收 |
| 可用渲染引擎 | Mermaid、PlantUML、draw.io、Archify；按需求选择引擎和导出格式 |

源码行校验能证明引用位置存在，不能单独证明业务关系、运行时行为或图面质量。[绘图规范](docs/DIAGRAM_STANDARD.md)说明图型选择和验收要求；[能力审计](docs/RENDERER_CAPABILITY_AUDIT.md)区分官方引擎能力、本项目的自动生成能力与原生文件通道。

### 四个渲染引擎分别能画什么

下表将**官方引擎的图型范围**、**本项目有确定性转换器的 IR v2 图型**和**可编写原生文件的图型**分开。官方目录会更新；原生图只有在当前安装的官方 CLI 实际验收成功后，才能算本机可交付。`architecture-landscape` 是本项目的架构总览约定，不宣称符合 C4 标准。

| 引擎 | 官方原生图型举例 | 本项目 IR v2 自动转换 | 其他图型的交付方式 |
|---|---|---|---|
| [Mermaid](https://mermaid.js.org/intro/syntax-reference.html) | 流程／泳道、时序、类、状态、ER、甘特、旅程、思维导图、C4 等 | C4 上下文／容器／组件、基础 UML 时序、ERD | 编写 `.mmd`，经 Mermaid CLI 验证和导出；C4 语法在 Mermaid 官方仍标为实验性 |
| [PlantUML](https://plantuml.com/) | UML 时序、用例、类、活动、组件、部署、状态、Timing；还有 ER、甘特、思维导图、JSON／YAML 等 | C4 上下文／容器／组件、基础 UML 时序、ERD | 编写 `.puml`，经 PlantUML CLI 验证和导出；活动图中的泳道等采用官方原生语法 |
| [draw.io](https://www.drawio.com/docs/diagram-types/) | C4、UML 多种结构／行为图、流程／泳道、BPMN、ER、云与网络架构等；形状和模板可自由组合，没有封闭的图型全集 | 架构总览、C4 上下文／容器／组件、基础 UML 时序、BPMN **可视子集**、ERD | 编写可编辑 `.drawio`，经 draw.io Desktop CLI 验证和导出；BPMN 可视图不等于可执行 BPMN XML |
| [Archify](https://github.com/tt-a1i/archify/blob/c826e6c3a7abad19c0f3cd1ca57207d54b1ad8de/archify/schemas/README.md) | 固定版本的五种 typed 图：architecture、workflow、sequence、dataflow、lifecycle | 暂无 IR v2 转换器；旧 IR v1 可转换为 architecture | 编写五种官方 typed JSON，经 Archify CLI 交付为交互 HTML，再按需导出 |

按官网目录细分，Mermaid 还包括用户旅程、饼图、象限、需求、用例、Git 图、时间线、ZenUML、Sankey、XY、Block、Packet、看板、Architecture、Radar、Event Modeling、Treemap、Venn、Ishikawa、Wardley、Cynefin、TreeView 等；完整且可能变化的清单以[官方语法目录](https://mermaid.js.org/intro/syntax-reference.html)为准。PlantUML 的 UML 图还包括对象图，其非 UML 图包括 EBNF、正则、网络图、Salt 界面图、ArchiMate、SDL、Ditaa、Chronology、WBS、IE／Chen ER 和图表等，详见[官方图型目录](https://plantuml.com/)。draw.io 是自由形状编辑器，除了上表还可绘制思维导图、甘特、看板、组织图、机架图等；其[官方示例目录](https://www.drawio.com/docs/diagram-types/)是示例集合，并非受限的类型清单。Archify 固定版本只有表中五种 schema 图型。

因此，“支持某种图”有两种用法：上表 IR v2 列可从本项目分型 IR 确定性转换；其他官方图型由 Skill 根据需求和证据编写原生图源，再用官方引擎验收。后者不是每种图都有独立的自动转换器。[完整差异与边界](docs/RENDERER_CAPABILITY_AUDIT.md)列出更多图型。

| 引擎 | 保留的图源／展示文件 | 本项目可请求的导出格式 |
|---|---|---|
| Mermaid | `.mmd` | SVG、PNG、PDF |
| PlantUML | `.puml` | SVG、PNG、PDF |
| draw.io | 可编辑 `.drawio` | SVG、PNG、JPG、PDF |
| Archify | typed JSON、交互 HTML | SVG、PNG、JPG、WebP、WebM、PDF |

HTML 是 Archify 的交互展示文件；其余三种引擎的 HTML 不是本项目当前的导出选项。PNG、JPG、PDF 等格式由所选引擎分别导出，不会先统一转成 SVG 再冒充目标格式。不支持的引擎与格式组合会报错。

## 安装与升级

从 0.4.x 升级时，在原仓库运行 `bash install.sh`。安装器会把本仓库拥有的 `understand-docs`、`understand-arch`、`understand-project` 及更早的旧名称链接迁移到 `project-docs` 集合，之后使用新名称调用；无关同名目录和链接会保留。新入口存在冲突时，安装器会在改动任何宿主链接之前退出。迁移后运行 `bash install.sh --doctor`，再刷新或重启宿主的 Skill 发现。

原有 `UNDERSTAND_PYTHON`、`UNDERSTAND_RENDERER_HOME`、各引擎 CLI 覆盖变量及共享引擎缓存路径继续有效。兼容脚本 `install-arch.sh` 仍只管理 Codex 的绘图入口，目标名称改为 `project-docs-diagram`；完整集合使用 `install.sh`。

[install.sh](install.sh) 默认把统一入口和三个专用 Skill 软链接到 Codex 的 `~/.codex/skills` 和 Claude Code 的 `~/.claude/skills`，并自动安装当前缺失的四个绘图引擎。两边共用本仓库文件，更新一次即可同步更新。安装前会检查所有目标路径，保留无关目录和软链接；本仓库拥有的旧名称链接会迁移。`--uninstall` 只移除本仓库拥有的 Skill 链接，**不会删除**可被其他项目复用的引擎。[Claude Code 官方文档](https://code.claude.com/docs/en/skills#choose-where-skills-load)确认个人 Skill 目录与软链接可用；这里支持的是本地 Claude Code，会话之外的 Claude 云端环境不读取本机目录。

| 安装命令 | 行为 |
|---|---|
| `bash install.sh` | Codex、Claude Code 均安装统一入口和三个专用 Skill；补齐全部缺失引擎 |
| `bash install.sh --engine drawio` | 两个宿主安装 Skill；只补齐 draw.io。`--engine` 可重复指定 |
| `bash install.sh --no-engines` | 只安装 Skill，并记录“不要自动安装引擎”的选择 |
| `bash install.sh --host claude --engine mermaid` | 只为 Claude Code 安装 Skill，只补齐 Mermaid |
| `bash install.sh --host all` | 为全部八个宿主安装四个 Skill；共用同一套绘图引擎 |
| `bash install.sh --host opencode --no-engines` | 只为 OpenCode 安装四个 Skill，跳过绘图引擎 |
| `bash install.sh --doctor` | 检查两个宿主的 Skill 链接和四个引擎；可配合 `--host`、`--engine`、`--no-engines` 缩小检查范围 |
| `bash install.sh --update` | 快进更新当前跟踪分支，重新安装集合与三个子 Skill，并同步四个绘图 CLI 到新版集合锁定的版本 |
| `bash install.sh --update-deps` | 不拉取仓库，只同步当前集合声明的绘图 CLI 与 Skill 链接 |
| `bash install.sh --update --no-engines` | 仅更新集合及三个子 Skill，保留原有引擎自动安装偏好 |
| `bash install.sh --uninstall --host all` | 从八个宿主移除本仓库拥有的 Skill 链接，保留共享引擎 |

`--host` 接受 `codex`、`claude`、`zcode`、`dsh`、`gemini`、`grok`、`pi`、`opencode`、`both`、`all`。默认及 `both` 仍只管理 Codex、Claude Code；`all` 显式选择全部八个宿主。该选项适用于安装、升级、依赖同步、诊断和卸载；后续管理时使用与安装时相同的宿主选择。普通安装使用 `--no-engines` 后，后续画图时 Skill 也不会擅自补装；再次显式运行带 `--engine` 的安装命令可解除这一选择。已装好的引擎会复用，无需每次重新安装。

### 宿主支持

2026-10-15 核对的官方加载规范如下。每个目标目录下软链接四个 Skill 目录，形成 `<skill-name>/SKILL.md` 布局，解析到本仓库的 `skills/`；脚本、引用和模板仍从真实 Skill 目录解析。安装器不依赖宿主 CLI，也不安装或升级宿主软件。

| 宿主 / `--host` | 本安装器管理的用户级目录 | 官方规范与加载方式 |
|---|---|---|
| Codex / `codex` | `${CODEX_HOME:-~/.codex}/skills`（沿用现有安装位置） | [Codex Skills](https://developers.openai.com/codex/skills/)；自然语言或 `$project-docs` |
| Claude Code / `claude` | `${CLAUDE_HOME:-~/.claude}/skills` | [Claude Code Skills](https://code.claude.com/docs/en/skills)；自然语言或 `/project-docs` |
| ZCode / `zcode` | `~/.zcode/skills` | [ZCode Skill](https://zcode.z.ai/cn/docs/skill)；设置 → 技能中刷新并启用，支持 `$project-docs` |
| DeepSeek Harness / `dsh` | `${DSH_HOME:-~/.dsh}/skills` | [官方 Skills 子系统](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/skills.md)；一层目录包含 `SKILL.md`，由文件系统 provider 发现、`skill` 工具加载 |
| Gemini CLI / `gemini` | `~/.gemini/skills` | [Gemini CLI Agent Skills](https://geminicli.com/docs/cli/skills/)；`/skills list` 检查，`/skills reload` 刷新，按宿主提示确认激活 |
| Grok Build / `grok` | `~/.grok/skills` | [xAI 官方 Skills 指南](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/08-skills.md)；`grok inspect` 检查，支持 `/project-docs` |
| pi coding agent / `pi` | `${PI_CODING_AGENT_DIR:-~/.pi/agent}/skills` | [pi 官方 Skills 文档](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/skills.md)；新会话发现，支持 `/skill:project-docs` |
| OpenCode / `opencode` | `${XDG_CONFIG_HOME:-~/.config}/opencode/skills` | [OpenCode Agent Skills](https://opencode.ai/docs/skills/)；从 YAML `name`、`description` 建立目录，经原生 `skill` 工具加载 |

pi 原仓库 `badlogic/pi-mono` 已迁移到 `earendil-works/pi`，见[作者说明](https://mariozechner.at/posts/2026-04-08-ive-sold-out/)；`mariozechner/pi-coding-agent` 在本次核对时返回 404。Grok 适配对象是 [Grok Build](https://grok.com/build)，不涵盖第三方同名 `grok-cli` 或云端聊天的本机目录访问。

多个宿主还支持 `.agents/skills` 等兼容路径；本安装器只管理上表目录，不扫描或清理其他来源。同名 Skill 可能被工作区、兼容目录或禁用配置遮蔽，应在宿主里核对实际来源。`--doctor` 验证本集合的链接、版本、旧链接和所选引擎，**不证明**宿主已启用、发现或执行 Skill；安装、卸载后需刷新或新建会话。现有的权限、信任和激活确认仍由各宿主管理。

新增宿主已覆盖隔离目录中的安装、幂等、升级转发、诊断、卸载、旧名迁移、路径冲突和 DSH／pi／XDG 目录覆盖回归；尚未逐一运行真实宿主会话。仅提供本机文件的安装适配，不保证云端或远程沙箱能读取本机路径。

例如只管理 pi：

```bash
bash install.sh --host pi --no-engines
bash install.sh --doctor --host pi --no-engines
bash install.sh --update --host pi --no-engines
bash install.sh --update-deps --host pi --no-engines
bash install.sh --uninstall --host pi
```

统一升级使用 `bash install.sh --update --host <宿主>`，也可在当前宿主中说“使用 project-docs 更新本集合及依赖”，由 Skill 显式传入对应 `--host`。升级读取当前 Git 分支的跟踪上游，不自动切换分支；本地有未提交或未跟踪文件、处于 detached HEAD、未配置上游或无法快进时会停止，不自动暂存、重置或覆盖本地改动。仓库更新成功后，用新版安装器同步链接与依赖；若后续依赖步骤失败，会明确返回失败，可解决原因后运行 `bash install.sh --update-deps --host <宿主>` 重试。

三个子 Skill 随同一仓库更新。四个绘图 CLI 按本集合锁定并验收的版本同步，保留下载校验；新版准备成功后才切换受管入口，旧版本目录保留。macOS 的 draw.io 更新安装在共享管理目录，Linux 使用现有 apt 安装流程，可能需要系统权限。`*_OFFICIAL_CLI` 显式指定的工具保留原路径并提示由外部管理；管理目录中的自定义入口也不会被强行覆盖。PDLC、understand-anything 和 CodeGraph 属于按需使用的外部能力，不作为本集合必装依赖，也不扫描升级用户的其他全局 Skill 或软件。

`--update`、`--update-deps` 均支持 `--engine mermaid` 等选项限定 CLI 范围；这两个命令中的 `--no-engines` 只跳过本次引擎同步，不改变原有自动安装偏好。普通生成任务不会在运行前自动联网升级。

### 渲染引擎要另外安装吗？

**通常不需要手动安装。**默认安装流程会检测并补齐四个引擎；也可用 `--engine` 只装实际需要的引擎。如果生成图时才发现缺少所选引擎，Skill 会在未选择 `--no-engines` 的前提下自动补装并重试。生成接口文档不需要绘图引擎。安装程序会使用本地已有命令，缺失时在用户目录安装固定版本或调用系统包管理器；无法完成时明确报错，不会假称导出成功。

| 选择的引擎 | 本机需要的程序 | 安装与运行条件 |
|---|---|---|
| Mermaid | `mmdc` | 自动准备 Node.js 22.13+，并安装 [Mermaid CLI](https://github.com/mermaid-js/mermaid-cli#installation) 12.0.0 |
| PlantUML | `plantuml` | 自动准备 Java 并下载校验 [PlantUML](https://plantuml.com/download) 1.2026.8 |
| draw.io | `drawio` | macOS 自动下载并校验 [draw.io Desktop](https://github.com/jgraph/drawio-desktop/releases) 29.3.6 通用版 DMG，安装在用户目录；x86-64 的 apt 系 Linux 使用校验过的 29.3.6 安装包，并准备无桌面环境导出所需的 Xvfb |
| Archify | `archify` | 自动准备 Node.js、Chrome/Chromium，并安装校验 [Archify](https://github.com/tt-a1i/archify/releases/tag/v2.16.0) 2.16.0 |

安装与内部 CLI 要求 **Python 3.11 或更新版本**；解析 Java 源码还需要 JDK 11 或更新版本。macOS 自动安装 Chrome／Java 需要 Homebrew；Linux 的系统包安装需要 apt 与相应权限。系统缺少这些条件、下载校验失败或格式不可用时会明确报错，不会悄悄换用其他引擎或格式。手动指定 CLI 路径的开发者可查看[Skill 入口说明](#文档)。

## 使用 Project Docs API

打开目标项目，在上表任一宿主中描述要生成的文档即可。例如：

```text
使用 $project-docs-api 为当前项目生成完整 API 文档，包含请求、响应、枚举说明、Postman 集合和 cURL 示例。
使用 $project-docs-api 只生成 OrderController 的 createOrder 接口文档。
使用 $project-docs-api 为这个 FastAPI 项目生成接口文档。
```

Skill 会定位源码并运行生成器；完整交付物包括 Markdown、Postman Collection 和 cURL 示例。若一个方法对应多个路由，它会明确选择具体 HTTP 方法与路径；若 DTO 来自另一个源码根或 JAR，则需要能访问该依赖。无法从源码确定的类型或示例值会标出，不会猜造真实请求。已有 CodeGraph 或 tree-sitter 可辅助定位，字段与枚举仍由源码解析。手动 CLI 参数保留在 [Project Docs API Skill](skills/project-docs-api/SKILL.md) 中，普通使用无需填写源码路径和命令参数。

## 使用 Project Docs Overview

在目标项目中描述读者和范围即可。Skill 根据[项目总览模板](skills/project-docs-overview/assets/project-overview.md)、[功能说明模板](skills/project-docs-overview/assets/feature-description.md)、[架构总览模板](skills/project-docs-overview/assets/architecture-overview.md)或[开发者上手手册模板](skills/project-docs-overview/assets/developer-guide.md)起稿，核对需求资料、代码、测试与实际命令，再生成带来源的 Markdown。默认保留所选模板的二级章节及顺序，资料不足的地方明确标为待确认；只有用户要求其他框架时才调整。架构总览吸收 PDLC 的系统全景、通信、数据、可观测性、扩展性与改进建议结构，并要求系统全景图和核心流程图；跨系统关系复杂时再补系统上下文图。图可嵌入本地图片并链接可编辑图源，或在支持 Mermaid 的交付环境中嵌入经过渲染检查的源码。评分需要逐项依据，缺少运行资料时写待评估。开发者手册包含从入口到关键规则与复杂模块的推荐阅读路线。默认写到目标仓库之外，除非明确要求更新仓库文档或发布到飞书。明确要求按 PDLC 阶段产出时，沿用 PDLC 自己的模板、目录与状态流程。

```text
使用 $project-docs-overview 为这个项目写一份给新同事看的介绍：业务目标、主要功能、端到端链路和模块职责。
使用 $project-docs-overview 说明退款功能的现状、判据表、改动点、验证场景与风险。
使用 $project-docs-overview 为新开发者生成上手手册，写明环境、启动、测试、文档索引和常见问题。
使用 $project-docs-overview 为这个系统写架构总览文档，包含系统全景架构图、核心流程图，以及模块边界、通信、数据与架构风险。
使用 $project-docs-overview 根据代码和最新 PRD 更新已有的项目介绍，保留人工补充内容。
```

只有源码时可以说明实际实现，不能从代码猜测产品决策、工期或上线状态；缺失口径会列为待确认。上手手册只列项目实际支持的命令，不假设存在 PDLC 的 `make status` 等入口。复杂链路可配图，接口字段细节继续交给 `project-docs-api`。架构总览交付时，Markdown、导出图片、可编辑图源与图形证据放在同一交付目录及其子目录内并使用相对链接；校验命令加 `--check-diagrams`，会调用已安装的官方引擎实际渲染 Mermaid 和链接的图源，并检查图片内容及路径。传入 `--source` 时，原生图需保留同目录的 v2 `diagram.evidence.json`；IR `deliver` 图需保留含 `manifest.json` 的完整 bundle。图与源码所表达的业务关系仍需人工复核。

写作前可用 [`project_doc_context.py`](scripts/project_doc_context.py) 按文件、符号或业务词提取聚焦上下文；它只引用已核实为新鲜的 understand-anything 图谱，过期图谱会被排除。更新已有文档时，[`project_doc_impact.py`](scripts/project_doc_impact.py) 根据文档记录的源码版本和引用，列出直接受影响章节及仍需人工检查的未映射文件。交付前以 `--source <目标仓库>` 运行 [`validate_project_doc.py`](scripts/validate_project_doc.py)，检查章节、版本、每章来源和本地来源行号；架构模式还检查必备图及本地图片路径，并要求五维评估完整、给分时逐项提供来源。业务解释与图示语义仍需人工核对。

## 使用 Project Docs Diagram

在 Codex 或 Claude Code 中说“根据代码生成架构图”即可开始。Skill 会按[绘图规范](docs/DIAGRAM_STANDARD.md)确定视图和引擎；明确要求 C4、流程图、泳道图、时序图或其他图型时，会采用对应记法。参考图和长提示词不是必需输入。

可以直接说目标，也可以显式触发 Skill 并指定引擎、图型、导出格式。下列示例使用 Codex 的 `$project-docs-diagram`；在 Claude Code 中将其写作 `/project-docs-diagram`：

```text
根据这个项目的代码生成架构图，导出 PNG。
使用 $project-docs-diagram 为 FA 模块画 draw.io 架构总览，并给复杂链路配细节图，导出 PNG。
使用 $project-docs-diagram 根据订单调用链画 PlantUML 时序图，保留 .puml，导出 PDF。
使用 $project-docs-diagram 根据状态转换画 Mermaid 状态图，保留 .mmd，导出 SVG。
使用 $project-docs-diagram 根据审批流程画 Archify workflow，保留 JSON 和交互 HTML，导出 WebP。
```

未指定引擎时，Skill 先按问题选图型，再选能表达该图型的引擎；项目／模块架构总览默认用 draw.io。明确指定引擎或导出格式时按要求执行；不支持的组合会报告错误。以上 Mermaid 状态图和 Archify workflow 走**官方原生图源通道**，不是 IR v2 转换。

Skill 会读取源码和可用的 CodeGraph 信息，选择合适的图型，生成可编辑图源，调用已安装的官方引擎导出指定格式，再核对源码证据与实际成图。已实现的图型使用[分型 IR v2](skills/project-docs-diagram/references/diagram-view-ir.md)；其他官方图型使用引擎原生文件和[证据清单](skills/project-docs-diagram/references/native-diagrams.md)。用户无需手写 IR、JSON 或执行 Python 命令。需要绕过 Codex 手动调用脚本时，参阅 [Project Docs Diagram Skill](skills/project-docs-diagram/SKILL.md) 中的命令行流程。

### 引擎如何参与生成

1. **发现与取证**：Skill 扫描仓库，并在已有且新鲜的 CodeGraph 索引可用时，借助它定位类、路由和调用关系；架构总览还会逐项核对候选模块与依赖。引擎本身不理解项目代码。
2. **生成图源**：已实现的图型由本项目将分型 IR 转换为 `.mmd`、`.puml` 或 `.drawio`；旧 IR v1 可转换为 Archify architecture JSON。其余图型由 Skill 编写对应引擎的原生语法或 typed JSON。
3. **调用官方引擎**：Mermaid、PlantUML、draw.io 解析各自图源并导出所需格式；Archify 验证 typed JSON，先生成交互 HTML，再由官方查看器导出图片和 WebM，或由浏览器打印 PDF。Skill 不把一个引擎的图偷偷交给另一个引擎处理。
4. **核查与交付**：源码图核对引用位置；架构总览连同声明的细节图一起交付。引擎通过只证明图源可解析、文件可导出；业务解释和图面效果仍需审阅。

证据清单的 `claimCoverage: complete` 表示图中材料已逐项关联源码，`claimSemantics: not_proven` 则表示业务解释仍需复核。旧[架构 IR v1](skills/project-docs-diagram/references/architecture-ir.md)继续兼容。

## 文档

- [Project Docs 统一入口](skills/project-docs/SKILL.md)
- [Project Docs API Skill](skills/project-docs-api/SKILL.md) · [API Document IR](references/api-document-ir.md)
- [Project Docs Diagram Skill](skills/project-docs-diagram/SKILL.md) · [图型与证据规范](docs/DIAGRAM_STANDARD.md)
- [Project Docs Overview Skill](skills/project-docs-overview/SKILL.md)
- [渲染引擎能力审计](docs/RENDERER_CAPABILITY_AUDIT.md) · [draw.io 模板取舍](docs/ARCHITECTURE_TEMPLATE_RESEARCH.md)
- [变更日志](CHANGELOG.md)

## 开发与验证

```bash
python3 -m unittest discover -s scripts -p 'test_*.py'
```

修改版本或用户可见行为时，同步更新 `VERSION` 和 `CHANGELOG.md`。修改 Skill 入口时，使用 Codex `skill-creator` 的 `quick_validate.py` 校验元数据与目录结构。真实引擎的可用性及图像质量需要对应 CLI 和成品检查；单元测试不替代这两项验收。

## 参考与鸣谢

感谢以下项目和实践。列出它们是说明能力来源与启发，并不表示这些项目为本仓库的生成结果背书。

- **API Savior IDEA 插件**：启发了接口文档的 RESTful 版式与字段呈现方式；本仓库实现的是独立的源码解析和命令行生成流程。
- [Mermaid](https://mermaid.js.org/)、[PlantUML](https://plantuml.com/) 与 [draw.io](https://www.drawio.com/)：提供图形语法、编辑器与实际渲染工具。
- [Archify](https://github.com/tt-a1i/archify)：提供 typed 图型及官方交付与导出能力。
- [CodeGraph](https://www.npmjs.com/package/@colbymchenry/codegraph) 与 [tree-sitter](https://tree-sitter.github.io/tree-sitter/)：提供可选的代码定位能力。
- [Converge Suite](https://github.com/ainiaa/skills-convergent-delivery)：本 README 的信息组织方式参考了该项目。

## 许可与反馈

[Apache License 2.0](LICENSE) · [GitHub Issues](https://github.com/ainiaa/skills-api-docs/issues)
