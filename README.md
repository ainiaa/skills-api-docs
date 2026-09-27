# API Savior Docs

面向 Codex 的 API 文档 Skill：从 Java/Spring MVC、Feign 或 Python/FastAPI 源码生成 Markdown 文档、Postman Collection 和 cURL 示例，无需启动 IntelliJ IDEA。

当前发布版本：[0.1.0](VERSION)。未发布改动见 [变更日志](CHANGELOG.md) 的 Unreleased。

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
python3 -m unittest test_generate_api_docs test_discovery test_install
```

测试覆盖 Java 与 Python 解析、文档生成，以及发现引擎的定位、自愈与增量再生（通过注入的 FakeEngine，无需安装 codegraph）。修改版本或用户可见行为时，同步更新 `VERSION` 与 [CHANGELOG.md](CHANGELOG.md)。修改 Skill 入口后，还应运行 Codex `skill-creator` 的 `quick_validate.py` 校验元数据和目录结构。

## 许可与反馈

[Apache License 2.0](LICENSE) · [GitHub Issues](https://github.com/ainiaa/skills-api-docs/issues)
