# Source-based diagram contract

本文件是 `understand-arch` 的绘图与验收契约。用户只需说“根据代码生成架构图”；Skill 应根据仓库证据选择图型与层级，交付可编辑源文件和所需导出。参考图只影响可选的视觉偏好，不是生成合格架构图的前提。

**可置信的含义**：逐项区分源码证据、CodeGraph 线索、图型语义校验、官方引擎解析、实际图片审查。任何一项通过都不能代替其他项；特别是“成功导出 PNG”不等于“架构图正确且可读”。

## 采用的规范与能力边界

架构、调用顺序、业务流程和数据结构不能共用一套图形语义。统一的是选图、取证和验收过程；具体图型按问题选择：

| 要回答的问题 | 图型 | 规范依据 | 默认引擎 | 其他引擎的边界 |
| --- | --- | --- | --- | --- |
| 项目／模块的入口、边界、核心职责及依赖是什么？ | 架构总览（`architecture-landscape`） | 本项目的源码取证与视觉约定；不宣称 C4 合规 | draw.io | 当前无其他引擎适配 |
| 系统由什么组成、依赖什么？ | C4 系统上下文／容器／组件 | [C4 model](https://c4model.com/diagrams) | draw.io | PlantUML C4；[Mermaid C4](https://mermaid.js.org/syntax/c4) 为实验性功能，必须标注 |
| 调用按什么顺序发生？ | UML 时序图 | [OMG UML 2.5.1](https://www.omg.org/spec/UML/2.5.1) | PlantUML | Mermaid 与 draw.io 均支持当前的参与者、调用、异步和返回消息子集 |
| 哪个角色执行哪个业务步骤？ | BPMN 2.0 可视子集 | [OMG BPMN 2.0.2](https://www.omg.org/spec/BPMN/2.0.2) | draw.io | Mermaid 流程图和 PlantUML 活动图不能冒称 BPMN |
| 实体怎样关联、基数是多少？ | Crow’s Foot ERD | [Mermaid ER](https://mermaid.js.org/syntax/entityRelationshipDiagram)、[PlantUML IE](https://plantuml.com/ie-diagram) | Mermaid | PlantUML IE 与 draw.io ER 连线 |

“BPMN 可视子集”表示使用事件、任务、网关、Pool、Lane、顺序流和消息流图形，并校验已实现的约束。`.drawio` 不是可执行 BPMN XML，本项目不声称通过 BPMN XML 一致性验证。C4 是建模约定，不是 OMG 标准。Mermaid C4 即使成功渲染，也仍有官方标注的实验性风险。

Archify 是独立的五型展示引擎；旧 IR v1 仅映射其 architecture 模式，原生通道可验收全部五种官方 JSON 模式。它不充当 C4、UML、BPMN 或 ERD 的规范导出器。

各官方引擎的图型目录大于上表的分型 IR 范围。对 IR v2 未覆盖的图型，Skill 按[原生绘图约定](../skills/understand-arch/references/native-diagrams.md)选择语义、核对代码、编写官方原生文件，再由 [`render_native_diagram.py`](../scripts/render_native_diagram.py) 交给 Mermaid、PlantUML、draw.io 或 Archify 官方 CLI 验证与导出；Archify 原生 JSON 覆盖官方五种模式。源码图须附逐条证据清单：`sourceEvidence: anchors_validated` 只证明图中文字及源码引文存在，`claimSemantics: not_proven` 提醒人工复核解释；未附清单时为 `sourceEvidence: not_checked`。完整差异见[渲染引擎能力审计](RENDERER_CAPABILITY_AUDIT.md)。

## 简短请求的默认行为

1. 先判定问题，再选引擎和格式。笼统的“项目／模块架构图”默认交付架构总览，包含源码支持的入口、真实模块边界、关键服务、数据设施与外部依赖。显式要求 C4 或某个 C4 层级时才交付 C4 图。总览使用可编辑 draw.io 原生形状和关系索引；它不是 C4、UML 或 BPMN 的替代规范。一个结构图不混放类、表、流程步骤和服务。
2. 业务流程选 BPMN，调用时序选 UML 时序图，实体关系选 ERD。若要求数据流，须明确数据流图的图型范围；不能把普通流程图默称正式 DFD。
3. 用户指定的引擎和格式在图型支持时照办。不支持的组合明确报错；不暗换图型，不对近似图宣称严格合规。
4. 未指定格式时，架构图交付可编辑 draw.io 与 PNG，时序图交付 PlantUML 与 PNG，BPMN 交付 draw.io 与 PNG，ERD 交付 Mermaid 与 PNG。官方引擎缺失时必须说明，不能计作验证通过。

## 源码证据与 CodeGraph

**被分析仓库**存在 `.codegraph/` 时，CodeGraph 优先提供类、路由和调用链候选。使用前检查索引是否有待处理变更、工作树不匹配或重建提示。索引过期或 CLI 不可用时退回源码核实并说明。图谱不能代替业务判断：调用和导入是代码事实，C4 容器与组件是对事实的归纳。

`context` 命令记录结构化类、路由，以及指定 `--focus` 符号的直接调用。每个图中断言仍需附仓库相对路径、从 1 开始的行号及源码原文片段。CodeGraph ID 只保留在机器可读证据中，不显示为图上标签。只汇总源码支持的关键跨边界关系；无法消除歧义的结论标记 `AMBIGUOUS`。

旧 IR v1 及其产物继续兼容；七种已支持 profile 的新图使用分型 IR v2，记录图型、范围、标题、元素、关系、来源判断和源码证据。其他官方图型用原生绘图约定。架构总览要求节点角色和链路分类，限制单图为最多 12 个元素与 12 条关系，并限制标签长度；超限时拆为概览和聚焦图。新总览在 `coverage.omitted` 记录移至细节图的源码事实，校验器验证对应细节 IR 含有该节点或关系。时序、BPMN、ERD 各有专用字段；通用节点／连线不足以准确表达顺序、网关或基数。IR v2 渲染前拒绝错误元素类型、C4 层级混用、缺失端点、无标签关系、非法流向和无证据断言；`EXTRACTED` 名称及关系标签必须逐字出现在引用源码。

## 交付验收

交付产物需要逐项通过适用的检查：

1. **证据**：引用的源码位置与原文一致；逐字提取与推断分开标注，说明图谱新鲜度和不确定解释。原生图证据清单 v2 须覆盖已识别的材料行／单元／typed 项；总览须说明省略事实及配套细节图。覆盖校验仍不能发现作者从未列出的候选关系。
2. **语义**：图型、范围、元素和关系类型以及专用约束通过。C4 组件图有单一容器范围，关系具有方向和意图；BPMN 顺序流留在同一 Pool，消息流跨 Pool；ERD 两端基数明确。
3. **渲染**：官方引擎解析可编辑文件，且请求的导出文件结构有效。这只证明语法和导出能力。
4. **视觉**：实际打开图片，检查标签、边界、遮挡、线条密度、无意义 ID、标题与图例。图太密时拆为总览与细节，保留所需证据。
5. **回归**：覆盖正常、边界、非法输入、过期图谱、不支持的引擎，以及此前 FA 模块布局失败；支持的组合以官方引擎实测后才宣布可用。

自动解析不能证明所有业务边界和视觉判断。报告必须区分源码核实的事实、推断的架构、引擎检查和人工审图结果；不能以“PNG 导出成功”代替架构质量结论。

## 实现与回归记录（2026-09-28）

| 验收项 | 已执行证据 | 结论 |
| --- | --- | --- |
| IR v1 向后兼容及原生通道 | `python3 -m unittest discover -s scripts -p 'test_*.py'` | 运行 235 个，7 个可选环境测试跳过，其余通过 |
| 图型语义和异常路径 | `test_diagram_profiles.py` 覆盖 C4 层级、时序顺序、BPMN 跨 Pool 规则、ERD 基数、缺证据、过期 CodeGraph 与不支持的引擎 | 通过 |
| 官方引擎 | 同一测试以本机 `drawio`、`plantuml`、`mmdc` 实际解析 C4、UML 时序、BPMN 可视子集、ERD | 通过；Mermaid C4 仍按官方定义标记为实验性 |
| CodeGraph 真实仓库 | 对 FMS 仓库 `a351e2fd771c98f31ccaea3a0ef4d8e9adfd11cf` 运行 `context --focus FaAssetManageController.modifyEventPush` | 读取 577 个类、86 条路由和 4 个聚焦直接调用；独立源码证据仍须核实 |
| FA 架构图回归 | 原版 C4 组件图虽经 draw.io 导出，却未达到用户要求的边界和链路表达 | 原“可读”结论撤回；导出成功不构成视觉验收 |
| draw.io 时序图回归 | 以同一 FA 仓库 Controller → Service → Repository 源码证据生成 `.drawio`，官方 CLI 导出 PNG，并实际打开图片检查 | 生命线、消息顺序、调用箭头和返回虚线可读；复杂 UML 片段框尚未实现 |
| Skill 与工作区 | Skill Creator `quick_validate.py`、`git diff --check` | 通过 |

本轮保留旧的 IR v1 通用渲染器作为兼容路径。已支持的架构 profile 走分型 IR v2；其他官方图型走原生绘图约定。CodeGraph 是事实线索，最终模块归并与业务边界仍需源码审阅。CLI 返回 `visualReview: required`，不伪造自动视觉通过。BPMN 的 IR v2 适配当前只支持注明的可视子集，未输出可执行 BPMN XML。

## FA 视觉问题的二次验收（2026-09-28）

- [模板调研](ARCHITECTURE_TEMPLATE_RESEARCH.md)说明了为什么没有直接套用 GitHub 的固定坐标文件；新总览使用原生 draw.io 形状和动态主题。
- FA 源码证据生成 9 节点／8 关系总览，并拆出资产事件、分类账簿、残值三个聚焦图；17 条详细关系全部由聚焦图覆盖，未为降低密度而丢弃。
- 17 关系的单张总览被密度校验明确拒绝；FA 真实仓库的四张图均通过源码锚点校验和本机 draw.io 官方 CLI PNG 导出，并已打开图片审查边界、标签、连线及遮挡。
- `python3 -m unittest discover -s scripts -p 'test_*.py'`：239 个测试通过，7 个可选环境测试跳过；Skill Creator `quick_validate.py`、`git diff --check` 与 `install-arch.sh --doctor` 通过。这里的视觉审查是本次样例结论，不代表算法能自动证明任意仓库的美观或业务正确性。
