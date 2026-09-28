# API Savior Docs 与 Understand Arch

本仓库包含两个面向 Codex 的 Skill：`api-savior-docs` 从 Java/Spring MVC、Feign 或 Python/FastAPI 源码生成接口文档；`understand-arch` 从源码证据起草和校验架构 IR，再生成多种架构图。

当前开发版本：[0.3.0-dev](VERSION)。未发布改动见[变更日志](CHANGELOG.md)。

## Understand Arch

`skills/understand-arch/SKILL.md` 是独立入口，API 文档的 `ApiDocument` IR 和生成器保持原有用途。安装新 Skill：

```bash
bash install-arch.sh
bash install-arch.sh --doctor
```

可在 Codex 中直接请求“根据代码生成架构图”，或显式使用 `$understand-arch`。笼统的项目／模块架构图默认生成有源码证据的 draw.io 架构总览，显示入口、模块边界、业务服务、数据设施和外部依赖；明确要求 C4 时使用 C4 图型。Skill 也可选择 UML 时序、BPMN 业务流程或 ERD；参考图和长提示词不是前提。UML 时序图可由 PlantUML、Mermaid 或 draw.io 输出，默认选择 PlantUML。CodeGraph 索引存在且新鲜时，`context` 会读取结构化类、路由及通过 `--focus <方法>` 指定的直接调用，作为源码取证线索。新图使用[分型 IR v2](skills/understand-arch/references/diagram-view-ir.md)，旧[架构 IR v1](skills/understand-arch/references/architecture-ir.md)继续兼容。完整的图型选择、能力边界和验收要求见[绘图规范](docs/DIAGRAM_STANDARD.md)。无模型的 CLI 也可独立使用：

```bash
python3 scripts/generate_architecture.py context --source /path/to/repo --output /tmp/arch-context.json
python3 scripts/generate_architecture.py validate --source /path/to/repo --ir /tmp/architecture-ir.json
python3 scripts/generate_architecture.py render --source /path/to/repo --ir /tmp/architecture-ir.json --output /tmp/architecture --format drawio --export-for drawio:png
```

官方引擎支持的图型多于分型 IR v2。对未覆盖的图型，Skill 可根据需求和代码证据编写官方原生 `.mmd`、`.puml`、`.drawio` 或 Archify typed `.json`，再用统一命令交给相应官方 CLI 验证并按需导出。已有原生文件也可直接走此通道。例如：

```bash
python3 scripts/render_native_diagram.py --engine mermaid --input /tmp/classes.mmd --output /tmp/classes --export png
python3 scripts/render_native_diagram.py --engine archify --input /tmp/process.workflow.json --output /tmp/process --export png
python3 scripts/render_native_diagram.py --engine mermaid --input /tmp/classes.mmd --output /tmp/classes \
  --source-repo /path/to/repo --evidence /tmp/diagram.evidence.json --export png
```

Archify 原生通道接受官方 `architecture`、`workflow`、`sequence`、`dataflow`、`lifecycle` 五种模式。源码驱动的原生图须附[证据清单](skills/understand-arch/references/native-diagrams.md)：v2 清单逐项覆盖图中的材料并关联当前源码行；回执会报告 `sourceEvidence: anchors_validated`、`claimCoverage: complete` 和 `claimSemantics: not_proven`。没有清单则报告 `sourceEvidence: not_checked`。`officialCheck: pass` 只表示原生文件经官方引擎验收，图的业务解释和视觉质量仍要审阅。各引擎官方目录与当前自动生成缺口见[能力审计](docs/RENDERER_CAPABILITY_AUDIT.md)。

`context` 不设模块、类或文件数量上限，列出所有源码文件及扫描到的声明、路由、配置键和表名线索；声明扫描复用现有 tree-sitter 解析能力（未安装可选语法包时退回逐行候选扫描）。已有 `.ua/knowledge-graph.json` 与 `domain-graph.json` 时也会提供给 agent，并报告提交版本不一致。源码行校验能拦截不存在的引用；新鲜图谱或现有 CodeGraph 索引还会核对关键类的位置。业务能力和关系仍是带证据的推断，需审阅 `INFERRED`／`AMBIGUOUS` 项。`render` 用可重复的 `--format` 选择引擎，默认只交付原生文件与已验证 IR；`--export-for 引擎:格式` 按需求追加实际渲染的文件。选中 Archify 且 CLI 可用时会交付 HTML。`rendererChecks` 记录所选 Mermaid、PlantUML、draw.io 引擎的语法与导出验收状态，不能替代实际图片审查；新 IR v2 的回执标记 `visualReview: required`。Archify 使用 `archifyRendered` 和 `archifyReceipt`。任一请求的导出失败时命令返回非零，并清理对应旧成品。

### Mermaid、PlantUML、draw.io 官方验收

按需要选择一种或多种格式；要强制所选格式经过对应引擎验收，传入官方 CLI 路径：

```bash
python3 scripts/generate_architecture.py render \
  --source /path/to/repo --ir /tmp/architecture-ir.json --output /tmp/architecture \
  --format mermaid --format plantuml --format drawio \
  --mermaid-cli /path/to/mmdc --plantuml-cli /path/to/plantuml \
  --drawio-cli /path/to/drawio
```

默认交付物分别是 `.mmd`、`.puml`、`.drawio`。Mermaid 和 draw.io 会在临时目录渲染以验证文件，PlantUML 使用 `-checkonly`；临时文件不会交付。需要静态文件时追加并重复 `--export-for`，例如 `--export-for mermaid:png --export-for drawio:jpg --export-for plantuml:pdf`。旧参数 `--svg-for mermaid` 仍可用，等价于 `--export-for mermaid:svg`。请求导出时必须能运行对应官方 CLI；产物经过格式签名检查后才列入 `artifacts`，失败时返回非零并清理旧文件。CI 固定 Mermaid CLI `12.0.0`、PlantUML `1.2026.8`、draw.io Desktop `29.3.6` 并执行真实引擎验收。引擎验收证明文件可渲染，业务解释仍需按 IR 证据审阅。

| 引擎 | 原生交付 | 可请求的静态导出 |
|---|---|---|
| Mermaid | `.mmd` | SVG、PNG、PDF |
| PlantUML | `.puml` | SVG、PNG、PDF |
| draw.io | `.drawio` | SVG、PNG、JPG、PDF |
| Archify | `.archify.json`、HTML | SVG、PNG、JPG、WebP、WebM、PDF |

Archify 官方 CLI 先交付并验收 HTML；请求图片或 WebM 时，本脚本用 Chrome/Chromium 调用该 HTML 查看器的官方导出菜单，PDF 调用同一浏览器的打印功能。请求 WebM 会为该次 Archify 规格启用 `trace` 动画。需有 Node.js 和 Chrome/Chromium；浏览器不支持 WebM 录制时会明确失败。成功文件会列入 `artifacts`。不支持的引擎与格式组合会在写文件前拒绝。

### Archify 官方验收

需要声称 Archify 成品通过官方验收时，传入固定版本 CLI 的路径：

```bash
python3 scripts/generate_architecture.py render \
  --source /path/to/repo --ir /tmp/architecture-ir.json --output /tmp/architecture \
  --format archify \
  --archify-cli /path/to/archify/archify/bin/archify.mjs
```

此模式要求 CLI 可用，并调用官方 `deliver --quality showcase --json`。成功结果中的 `archifyReceipt` 包含官方校验和成品检查回执；失败返回非零状态。附加 `--export-for archify:png --export-for archify:pdf` 等参数即可交付查看器导出的静态文件。CI 的 [Archify 验收工作流](.github/workflows/archify-acceptance.yml)固定官方 [v2.16.0](https://github.com/tt-a1i/archify/releases/tag/v2.16.0) 对应提交 `c826e6c3a7abad19c0f3cd1ca57207d54b1ad8de`，用真实 CLI 测试含多个业务域、两张表、外部系统和关系的适配器输出。官方 `deliver` 包含验证、渲染及最终成品检查；它不证明业务域解释正确，`INFERRED`／`AMBIGUOUS` 仍需人工审阅。

## 3 步快速开始

1. 克隆仓库，并安装到 Codex：

   ```bash
   git clone https://github.com/ainiaa/skills-api-docs.git
   cd skills-api-docs
   bash install.sh
   ```

2. 运行 `bash install.sh --doctor` 确认安装，然后重启或刷新 Codex 的 Skill 发现。

3. 显式调用 Skill：

   ```text
   使用 $api-savior-docs 为这个 Spring Controller 生成 API 文档，包含 requestBody 和枚举说明。
   ```

## 为什么会有它

API Savior 插件在 IDEA 中读取映射注解与 DTO 来生成接口文档。本 Skill 把这类文档生成能力带到 Codex 和命令行中：从源码解析入参、出参、字段说明与枚举，生成 Markdown、Postman 和 cURL 三种结果。

## 能力与边界

| 输入 | 当前支持 |
|---|---|
| Java | Spring MVC Controller、Feign Client、映射注解、DTO 字段与泛型、源码可解析的枚举 |
| Python | FastAPI 路由、`APIRouter`、参数绑定、应用／路由／挂载依赖中的请求参数与响应类型 |
| 输出 | Markdown、Postman Collection、cURL 示例 |

Java 文档包含 JSON 请求体示例、分层字段表，以及字段内和独立章节中的枚举说明。对于无法从源码确定的类型或枚举值，生成器保留未解析状态，不猜测真实请求值。

解析基于提供的源码，不加载 IDEA 项目模型。JAR DTO 按完整类名解析，并展开可用的父类字段；同名类缺少明确导入时给出歧义提示。二进制 JAR 不能提供完整的枚举元数据；未解析的 DTO 和非 JSON 请求体不会生成猜测的 JSON 内容。如果需要与某个已安装插件版本逐字一致，应对同一接口比较两边的实际输出。IDEA 中的导航、UI 操作和代码生成不在本 Skill 的范围内。

## 安装与升级

仓库根目录就是 Skill 目录，入口为 [SKILL.md](SKILL.md)。[install.sh](install.sh) 将当前仓库软链接到 `${CODEX_HOME:-$HOME/.codex}/skills/api-savior-docs`，重复安装安全，不覆盖已有目录、文件或其他软链接。

更新仓库后运行 `bash install.sh --doctor` 检查软链接，再重启或刷新 Codex 的 Skill 发现。`bash install.sh --uninstall` 只移除指向当前仓库的软链接。不要把生成的 API 文档写入源码目录，除非你明确要将其纳入项目。

## 调用当前 Skill

在 Codex 中可显式使用 `$api-savior-docs`，也可直接运行 CLI。运行脚本需要 Python 3.9 或更新版本；Java 源码解析还需要 JDK 11 或更新版本。

```bash
python3 scripts/generate_api_docs.py \
  --source /path/to/project/src/main/java \
  --output /tmp/api-savior-docs
```

只生成一个 Java 接口的 Markdown 文档：

```bash
python3 scripts/generate_api_docs.py \
  --source /path/to/project/src/main/java \
  --controller /path/to/project/src/main/java/example/OrderController.java \
  --endpoint createOrder \
  --output-file /tmp/create-order.md
```

同名重载方法或一个方法对应多个路径/HTTP 方法时，使用 `--endpoint createOrder@POST:/orders` 精确选择；只写方法名会报歧义并列出可选值。仓库含 `.codegraph/` 索引时 `--controller` 可省略，生成器会自动定位。

FastAPI 源码使用 `--language python`。多个源码根目录可重复传入 `--source`；Java 的二进制 DTO 依赖可重复传入 `--classpath`。完整参数见 `python3 scripts/generate_api_docs.py --help`。`curl.sh` 在未指定 `--base-url` 时以 `http://localhost:8080`（Java）或 `http://localhost:8000`（Python）作为示例地址，发送前请替换为实际服务地址。

## 可选：代码发现引擎（codegraph / tree-sitter）

生成器可以自动利用代码发现引擎完成三件事，无需改变调用方式（Java 与 Python 均支持）：

- `--endpoint` 不再需要先传 `--controller`：按接口方法名定位声明文件。Java 会据此缩小扫描范围；Python 的模块名由传入源码根决定，为保证输出一致仅输出定位提示、不收窄；
- 报出未解析 DTO 类型时，自动反查类型定义文件、推导其源码根并重跑（最多 2 轮，stderr 以 `[引擎名]` 前缀说明补了什么；Python 包根按 `__init__.py` 链推导）；
- `--changed <改动文件>`：只重新生成受改动影响的接口段落，覆盖 Controller/路由源文件本身与 DTO 的传递引用（例如接口返回 `PageData<Order>`，改 `Order.java` 同样命中）。

引擎按可用性自动选择，互为备选：

1. **codegraph**（推荐）：仓库含 `.codegraph/` 索引且安装了 [codegraph CLI](https://www.npmjs.com/package/@colbymchenry/codegraph)，先增量 `sync` 再查询，覆盖整个项目；`--changed` 的批量定位在引擎内并行执行；
2. **tree-sitter 回退**：安装可选包 `pip3 install tree-sitter tree-sitter-python tree-sitter-java tree-sitter-typescript tree-sitter-go tree-sitter-php` 后生效。符号索引覆盖 `.java` / `.py` / `.ts` / `.tsx` / `.go` / `.php`，主查询逐字 vendor 自各语法上游仓库的 tags.scm；项目边界取最近的 `.git` 祖先目录；按文件的 mtime+size 缓存放系统临时目录，查询文本变更自动失效。两者都不可用时不启用任何引擎。

发现引擎只回答"文件与符号在哪"。字段、wire 名、枚举等语义仍由源码解析产生——文档生成适配器目前为 Java（Spring/Feign）与 Python（FastAPI），新语言接入引擎后即可被定位，待对应框架适配器出现后即可生成文档。`--no-codegraph` 显式关闭整个发现层。

## 生成结果

传入 `--output` 时，会在指定目录生成：

| 文件 | 内容 |
|---|---|
| `api-docs.md` | 接口说明、入参和出参字段、JSON 示例、枚举表 |
| `postman-collection.json` | 可导入 Postman 的请求集合 |
| `curl.sh` | 对应的 cURL 请求示例 |

示例值可能只是字段含义占位符。实际发送请求前，应替换为目标环境接受的值。

## 文档

- [Skill 使用规则](SKILL.md)
- [API Document IR](references/api-document-ir.md)：语言适配器与输出渲染器之间的数据结构

## 开发

```bash
cd scripts
python3 -m unittest test_generate_api_docs test_discovery test_install test_architecture test_install_arch
```

测试覆盖 Java 与 Python 解析、文档生成，以及发现引擎的定位、自愈与增量再生（通过注入的 FakeEngine，无需安装 codegraph）。修改版本或用户可见行为时，同步更新 `VERSION` 与 [CHANGELOG.md](CHANGELOG.md)。修改 Skill 入口后，还应运行 Codex `skill-creator` 的 `quick_validate.py` 校验元数据和目录结构。

## 许可与反馈

[Apache License 2.0](LICENSE) · [GitHub Issues](https://github.com/ainiaa/skills-api-docs/issues)
