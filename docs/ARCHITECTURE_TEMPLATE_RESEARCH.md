# draw.io 架构模板取舍

本轮审查了 [draw.io 官方 GitHub 模板说明](https://www.drawio.com/docs/diagram-types/template-diagrams-on-github/)、[jgraph/drawio-diagrams](https://github.com/jgraph/drawio-diagrams) 与一个 [MIT 架构／基础设施模板](https://github.com/iOSonntag-templates/drawio-infrastructure)。它们可以在编辑器里作为人工绘图起点，但现成模板保存的是特定节点、关系和坐标。直接替换文字无法根据任意仓库自动决定边界、节点数量、证据与路由，也无法解决 FA 图第一次出现的拥挤问题。

因此，自动绘图使用仓库内的 `architecture-landscape` 动态模板：固定视觉语法（角色形状、配色、模块边界、层次、链路线型、关系索引），按 IR 的节点和关系计算坐标，并对单图密度与标签长度设门槛。它只使用 draw.io 原生形状，不复制第三方模板文件或素材，不增加依赖。日后引入第三方图标或背景时，先逐项核对许可证、来源和不同节点数下的布局效果。

这一选择保留了 GitHub 模板可借鉴的视觉一致性，同时把图的内容和结构交给源码证据与语义校验。官方 CLI 导出通过仍须实际打开图片审查。
