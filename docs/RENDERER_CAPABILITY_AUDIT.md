# 渲染引擎图型能力审计（2026-09-28）

本审计区分四层含义：**官方引擎能画**、**本项目能调用官方引擎验证与导出原生文件**、**Skill 能依据需求和源码编写该原生文件并逐条核对源码锚点**、**本项目有确定性的分型 IR 转换器**。不能把任一层的验收结果扩大成另一层的证明。版本以 CI 固定的 Mermaid CLI 12.0.0、PlantUML 1.2026.8、draw.io Desktop 29.3.6、Archify 2.16.0（提交 `c826e6c3a7abad19c0f3cd1ca57207d54b1ad8de`）为实施基准；在线目录可能继续增加图型。

| 引擎 | 官方图型范围 | 本项目源码自动生成（IR v2） | 主要遗漏 |
| --- | --- | --- | --- |
| Mermaid | [官方图型目录](https://mermaid.js.org/intro/syntax-reference.html)列出流程、泳道、时序、类、状态、ER、旅程、甘特、饼图、象限、需求、用例、Git 图、C4、思维导图、时间线、ZenUML、Sankey、XY、Block、Packet、Kanban、Architecture、Radar、Event Modeling、Treemap、Venn、Ishikawa、Wardley、Cynefin、TreeView 等 | C4 上下文／容器／组件、基础时序、Crow’s Foot ERD；旧 IR v1 有业务域 flowchart | 独立流程／泳道、类、状态及其余官方语法均未接入分型 IR；C4 官方仍为实验性 |
| PlantUML | [官方目录](https://plantuml.com/)包含 UML 时序、用例、类、活动、组件、状态、对象、部署、Timing；还包含 JSON/YAML、EBNF、正则、网络、Salt、ArchiMate、甘特、思维导图、WBS、IE/Chen ER、图表等 | C4 上下文／容器／组件、基础时序、IE ERD；旧 IR v1 有业务域 component 图 | UML 类／活动／状态／部署等以及大多数非 UML 图型未接入分型 IR |
| draw.io | [官方示例目录](https://www.drawio.com/docs/diagram-types/)列出 C4、UML 多种结构和行为图、云与网络、流程、泳道、BPMN、ERD、思维导图、甘特、看板等；其模板和形状可自由组合，**没有封闭的全部图型枚举** | C4 上下文／容器／组件、基础 UML 时序、BPMN 可视子集、Crow’s Foot ERD；旧 IR v1 有业务域概览 | 类、活动、状态、部署、通用流程／泳道等没有专用分型 IR；BPMN 和时序也只覆盖已实现子集 |
| Archify | 固定版本有 [5 种 typed schema](https://github.com/tt-a1i/archify/blob/c826e6c3a7abad19c0f3cd1ca57207d54b1ad8de/archify/schemas/README.md)：architecture、workflow、sequence、dataflow、lifecycle | 仅旧 IR v1 → architecture schema-v1 | workflow、sequence、dataflow、lifecycle 未通过本项目适配器交付；官方自身已可处理其原生 JSON |

## 必须如实标注的差异

1. `generate_architecture.py render` 接收本项目 IR；`render_native_diagram.py` 接收 Skill 新编写或用户已有的 `.mmd`、`.puml`、`.drawio` 或 Archify typed JSON，并由相应官方引擎验证／导出。源码图附 `--source-repo` 与 `--evidence` 后，原生通道逐条验证图中文字和源码行引用；不声称推断的业务语义已被机器证明。
2. 当前分型 IR v2 只有 `c4-context`、`c4-container`、`c4-component`、`uml-sequence`、`bpmn-process`、`erd` 六个 profile；支持矩阵以 [`CAPABILITIES`](../scripts/diagram_profiles.py) 为准。
3. IR v1 的 Mermaid `flowchart`、PlantUML `component` 和 Archify `architecture` 是旧业务域概览；不能据此宣称支持 Mermaid 全部流程语义、UML 组件规范或 Archify 其余四种模式。
4. 文字源文件由引擎成功解析，只证明其官方语法成立；证据清单验证只证明引用和图中原文字段存在。从代码推断的关系仍须人工复核。draw.io 的自由形状没有有限的“官方全部图型”测试矩阵。
5. [C4 官方](https://c4model.com/diagrams)除系统上下文、容器、组件外，还有代码层以及系统全景、动态和部署辅助图；[Mermaid C4](https://mermaid.js.org/syntax/c4)的实验性语法也列出 Dynamic 与 Deployment。当前分型 IR 尚未覆盖这些视图，不能把“三层 C4 已支持”写成“全部 C4 图已支持”。

## 已实现的补缺与剩余边界

四个引擎已有原生通道：Skill 可针对 IR v2 之外的图型编写官方原生文件，由实际官方 CLI 验证并按需导出。源码驱动时使用[证据清单](../skills/understand-arch/references/native-diagrams.md)逐条关联图中内容与源码；CLI 在导出前核对引擎、Archify 类型、图中文字、源码路径／行号／逐字引用。通过时回执标记 `sourceEvidence: anchors_validated`、`claimSemantics: not_proven`；无证据清单则为 `not_checked`。Archify 的五种固定模式均已用所安装的 2.16.0 官方示例测试，其中架构模式还验证了 PNG 导出。Mermaid 类图、PlantUML 活动图和 draw.io 自由形状图也已走官方 CLI。任意其他图型只在其原生文件由**当前固定版本**的官方 CLI 实际验收成功后才可称为“原生渲染支持”。

本轮完整回归执行 `python3 -m unittest discover -s scripts -p 'test_*.py'`：运行 235 个测试，7 个可选环境测试跳过，其余通过；Skill Creator 校验、Python 编译检查和 `git diff --check` 通过。另用本仓库真实测试类源码编写 Mermaid 类图和 3 条证据，官方 CLI 导出 PNG，打开图片确认类名及两个方法可读。CI 分别在固定版本的三种通用引擎作业和 Archify 2.16.0 作业运行原生通道测试。CI 远端作业尚未在本地执行，不能把本地结果写成远端通过。

源码图的交付有两条路径：六种已实现 profile 由确定性 IR 转换；其他官方图型由 Skill 根据代码事实编写原生格式，再经证据清单、官方引擎和视觉审查。后一路能覆盖所安装引擎实际接受的语法，并保留可编辑文件，但具体语义取决于源码解释和审阅；不能写成每种官方图型都有独立、确定性的自动转换器。特别是 Archify workflow／sequence／dataflow／lifecycle 可由 Skill 编写并交付官方原生 JSON，但尚无本项目 IR v2 转换器；Mermaid 和 PlantUML 的其他图型同理。draw.io 的开放形状体系也无法用封闭名单列出全部图型。
