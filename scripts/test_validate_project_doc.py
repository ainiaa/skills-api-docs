import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
VALIDATOR = REPOSITORY / "scripts" / "validate_project_doc.py"
FEATURE_HEADINGS = (
    "1. 需求与业务口径",
    "2. 现状、约束与缺口",
    "3. 端到端链路",
    "4. 核心规则与方案",
    "5. 改动清单",
    "6. 验证场景",
    "7. 风险、依赖与待确认事项",
)
PROJECT_HEADINGS = (
    "1. 项目定位",
    "2. 功能地图",
    "3. 端到端主链路",
    "4. 模块职责与依赖",
    "5. 关键规则与边界",
    "6. 运行与运维入口",
    "7. 已知限制与待确认事项",
)
GUIDE_HEADINGS = (
    "1. 项目总览",
    "2. 环境准备",
    "3. 安装与启动",
    "4. 常用操作",
    "5. 开发约定",
    "6. 测试与验证",
    "7. 推荐阅读路线",
    "8. 文档索引",
    "9. 常见问题与排障",
)
ARCHITECTURE_HEADINGS = (
    "1. 系统全景",
    "2. 核心流程",
    "3. 服务与模块边界",
    "4. 通信机制",
    "5. 数据架构",
    "6. 可观测性",
    "7. 可扩展性",
    "8. 架构评估",
    "9. 问题清单与改进建议",
)


class ValidateProjectDocTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "document.md"

    def run_validator(self, kind, content, source=None, check_diagrams=False):
        self.path.write_text(content, encoding="utf-8")
        process = subprocess.run(
            [sys.executable, str(VALIDATOR), "--kind", kind, "--file", str(self.path),
             *(["--source", str(source)] if source else []),
             *(["--check-diagrams"] if check_diagrams else [])],
            text=True, capture_output=True, check=False,
        )
        return process.returncode, json.loads(process.stdout) if process.stdout else {"stderr": process.stderr}

    @staticmethod
    def document(title, headings):
        return "# " + title + "\n\n" + "\n\n".join(
            "## " + heading + "\n\n已核对的内容。" for heading in headings
        ) + "\n"

    @staticmethod
    def unrated_architecture(content):
        dimensions = ("服务与模块边界", "通信机制", "数据架构", "可观测性", "可扩展性")
        table = "| 维度 | 评分（1-5） | 依据及来源 |\n|---|---|---|\n" + "\n".join(
            f"| {name} | 待评估 | 缺少运行资料 |" for name in dimensions
        )
        return content.replace("## 8. 架构评估\n\n已核对的内容。", "## 8. 架构评估\n\n" + table)

    def test_accepts_complete_feature_document(self):
        content = self.document("商品退款", FEATURE_HEADINGS)
        content = content.replace("已核对的内容。", "### 处理说明\n\n已核对的内容。", 1)
        code, result = self.run_validator("feature", content)
        self.assertEqual(code, 0, result)
        self.assertTrue(result["valid"])

    def test_accepts_complete_project_document(self):
        code, result = self.run_validator("project", self.document("结算系统", PROJECT_HEADINGS))
        self.assertEqual(code, 0, result)
        self.assertTrue(result["valid"])

    def test_accepts_complete_developer_guide(self):
        code, result = self.run_validator("guide", self.document("结算系统开发者手册", GUIDE_HEADINGS))
        self.assertEqual(code, 0, result)
        self.assertTrue(result["valid"])

    def test_accepts_architecture_overview_with_evidence_and_unrated_dimension(self):
        source = self.path.parent / "source"
        source.mkdir()
        (source / "Service.java").write_text("class Service {}\n", encoding="utf-8")
        content = self.document("订单系统架构总览", ARCHITECTURE_HEADINGS).replace(
            "已核对的内容。", "已核对的内容。来源：Service.java#L1"
        ).replace("# 订单系统架构总览\n", "# 订单系统架构总览\n\n> 源代码版本：非Git仓库\n", 1)
        content = content.replace(
            "## 8. 架构评估\n\n已核对的内容。来源：Service.java#L1",
            "## 8. 架构评估\n\n| 维度 | 评分（1-5） | 依据及来源 |\n|---|---|---|\n"
            "| 服务与模块边界 | 3 | 入口已定位：Service.java#L1 |\n"
            "| 通信机制 | 待评估 | 缺少运行资料，待确认 |\n"
            "| 数据架构 | 3 | 数据入口已定位：Service.java#L1 |\n"
            "| 可观测性 | 待评估 | 缺少监控资料，待确认 |\n"
            "| 可扩展性 | 待评估 | 缺少压测资料，待确认 |"
        )
        content = content.replace(
            "## 1. 系统全景\n\n已核对的内容。来源：Service.java#L1",
            "## 1. 系统全景\n\n已核对的内容。来源：Service.java#L1\n\n"
            "```mermaid\nflowchart LR\n  Client --> Service\n```"
        ).replace(
            "## 2. 核心流程\n\n已核对的内容。来源：Service.java#L1",
            "## 2. 核心流程\n\n已核对的内容。来源：Service.java#L1\n\n"
            "```mermaid\nflowchart LR\n  Request --> Result\n```"
        )
        code, result = self.run_validator("architecture", content, source)
        self.assertEqual(code, 0, result)

        without_flow = content.replace("```mermaid\nflowchart LR\n  Request --> Result\n```", "流程文字说明。")
        code, result = self.run_validator("architecture", without_flow, source)
        self.assertNotEqual(code, 0)
        self.assertTrue(any("核心流程图" in problem for problem in result["problems"]), result)

        empty_flow = content.replace("```mermaid\nflowchart LR\n  Request --> Result\n```", "```mermaid\n \n```")
        code, result = self.run_validator("architecture", empty_flow, source)
        self.assertNotEqual(code, 0)
        self.assertTrue(any("核心流程图" in problem for problem in result["problems"]), result)

    def test_architecture_overview_rejects_missing_local_image(self):
        content = self.document("订单系统架构总览", ARCHITECTURE_HEADINGS).replace(
            "## 1. 系统全景\n\n已核对的内容。",
            "## 1. 系统全景\n\n![系统全景](missing.png)"
        )
        code, result = self.run_validator("architecture", content)
        self.assertNotEqual(code, 0)
        self.assertTrue(any("图片" in problem for problem in result.get("problems", [])), result)

    def test_architecture_overview_accepts_local_diagram_images(self):
        for name in ("panorama.svg", "flow.svg"):
            (self.path.parent / name).write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        content = self.document("订单系统架构总览", ARCHITECTURE_HEADINGS)
        content = content.replace("## 1. 系统全景\n\n已核对的内容。",
                                  "## 1. 系统全景\n\n![系统全景](panorama.svg)")
        content = content.replace("## 2. 核心流程\n\n已核对的内容。",
                                  "## 2. 核心流程\n\n![核心流程](flow.svg)")
        content = content.replace("## 8. 架构评估\n\n已核对的内容。",
                                  "## 8. 架构评估\n\n| 维度 | 评分（1-5） | 依据及来源 |\n|---|---|---|\n" +
                                  "\n".join(f"| {dimension} | 待评估 | 缺少运行资料 |" for dimension in (
                                      "服务与模块边界", "通信机制", "数据架构", "可观测性", "可扩展性")))
        code, result = self.run_validator("architecture", content)
        self.assertEqual(code, 0, result)

    def test_architecture_overview_rejects_invalid_svg_content(self):
        for name in ("panorama.svg", "flow.svg"):
            (self.path.parent / name).write_text("not an SVG", encoding="utf-8")
        content = self.document("订单系统架构总览", ARCHITECTURE_HEADINGS)
        content = content.replace("## 1. 系统全景\n\n已核对的内容。",
                                  "## 1. 系统全景\n\n![系统全景](panorama.svg)")
        content = content.replace("## 2. 核心流程\n\n已核对的内容。",
                                  "## 2. 核心流程\n\n![核心流程](flow.svg)")
        code, result = self.run_validator("architecture", self.unrated_architecture(content))
        self.assertNotEqual(code, 0)
        self.assertTrue(any("图片" in problem for problem in result["problems"]), result)

    def test_strict_diagrams_require_portable_image_and_editable_source(self):
        image = self.path.parent / "panorama.svg"
        image.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        outside = self.path.parent.parent / "outside.svg"
        outside.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        self.addCleanup(outside.unlink)
        content = self.document("订单系统架构总览", ARCHITECTURE_HEADINGS)
        content = content.replace("## 1. 系统全景\n\n已核对的内容。",
                                  "## 1. 系统全景\n\n![系统全景](panorama.svg)")
        content = content.replace("## 2. 核心流程\n\n已核对的内容。",
                                  "## 2. 核心流程\n\n![核心流程](../outside.svg)")
        code, result = self.run_validator("architecture", self.unrated_architecture(content), check_diagrams=True)
        self.assertNotEqual(code, 0)
        self.assertTrue(any("可编辑图源" in problem for problem in result["problems"]), result)
        self.assertTrue(any("交付目录" in problem for problem in result["problems"]), result)

    def test_architecture_overview_rejects_absolute_image_path(self):
        image = self.path.parent / "panorama.svg"
        image.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        content = self.unrated_architecture(self.document("订单系统架构总览", ARCHITECTURE_HEADINGS))
        content = content.replace("## 1. 系统全景\n\n已核对的内容。",
                                  f"## 1. 系统全景\n\n![系统全景]({image})")
        code, result = self.run_validator("architecture", content)
        self.assertNotEqual(code, 0)
        self.assertTrue(any("交付目录" in problem for problem in result["problems"]), result)

    @unittest.skipUnless(shutil.which("mmdc"), "Mermaid CLI is unavailable")
    def test_strict_diagrams_use_official_renderer(self):
        content = self.document("订单系统架构总览", ARCHITECTURE_HEADINGS)
        content = content.replace("## 1. 系统全景\n\n已核对的内容。",
                                  "## 1. 系统全景\n\n```mermaid\nflowchart LR\n  A --> B\n```")
        content = content.replace("## 2. 核心流程\n\n已核对的内容。",
                                  "## 2. 核心流程\n\n```mermaid\nflowchart LR\n  A -- bad -->\n```")
        code, result = self.run_validator("architecture", self.unrated_architecture(content), check_diagrams=True)
        self.assertNotEqual(code, 0)
        self.assertTrue(any("渲染" in problem for problem in result["problems"]), result)

    @unittest.skipUnless(shutil.which("mmdc"), "Mermaid CLI is unavailable")
    def test_strict_diagrams_accept_portable_images_and_native_sources(self):
        content = self.unrated_architecture(self.document("订单系统架构总览", ARCHITECTURE_HEADINGS))
        for number, name in ((1, "panorama"), (2, "flow")):
            (self.path.parent / f"{name}.svg").write_text(
                '<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
            (self.path.parent / f"{name}.mmd").write_text(
                "flowchart LR\n  A --> B\n", encoding="utf-8")
            heading = ARCHITECTURE_HEADINGS[number - 1]
            content = content.replace(
                f"## {heading}\n\n已核对的内容。",
                f"## {heading}\n\n![{name}]({name}.svg)\n\n[可编辑图源]({name}.mmd)",
            )
        code, result = self.run_validator("architecture", content, check_diagrams=True)
        self.assertEqual(code, 0, result)

    @unittest.skipUnless(shutil.which("mmdc"), "Mermaid CLI is unavailable")
    def test_strict_diagrams_validate_additional_views(self):
        content = self.unrated_architecture(self.document("订单系统架构总览", ARCHITECTURE_HEADINGS))
        for heading in ARCHITECTURE_HEADINGS[:2]:
            content = content.replace(f"## {heading}\n\n已核对的内容。",
                                      f"## {heading}\n\n```mermaid\nflowchart LR\n  A --> B\n```")
        content = content.replace("## 3. 服务与模块边界\n\n已核对的内容。",
                                  "## 3. 服务与模块边界\n\n```mermaid\nflowchart LR\n  A -- bad -->\n```")
        code, result = self.run_validator("architecture", content, check_diagrams=True)
        self.assertNotEqual(code, 0)
        self.assertTrue(any("3. 服务与模块边界" in problem and "渲染" in problem
                            for problem in result["problems"]), result)

    @unittest.skipUnless(shutil.which("mmdc"), "Mermaid CLI is unavailable")
    def test_strict_source_backed_diagrams_require_evidence_manifests(self):
        source = self.path.parent / "source"
        source.mkdir()
        (source / "Flow.txt").write_text("A --> B\n", encoding="utf-8")
        content = self.unrated_architecture(self.document("订单系统架构总览", ARCHITECTURE_HEADINGS))
        content = content.replace("# 订单系统架构总览\n", "# 订单系统架构总览\n\n> 源代码版本：非Git仓库\n", 1)
        content = content.replace("已核对的内容。", "已核对的内容。来源：Flow.txt#L1")
        content = content.replace("## 9. 问题清单与改进建议",
                                  "来源：Flow.txt#L1\n\n## 9. 问题清单与改进建议")
        for number, name in ((1, "panorama"), (2, "flow")):
            directory = self.path.parent / name
            directory.mkdir()
            (directory / "diagram.mmd").write_text("flowchart LR\n  A --> B\n", encoding="utf-8")
            (directory / "diagram.svg").write_text(
                '<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
            heading = ARCHITECTURE_HEADINGS[number - 1]
            content = content.replace(
                f"## {heading}\n\n已核对的内容。来源：Flow.txt#L1",
                f"## {heading}\n\n![{name}]({name}/diagram.svg)\n\n"
                f"[可编辑图源]({name}/diagram.mmd)\n\n来源：Flow.txt#L1",
            )
        code, result = self.run_validator("architecture", content, source, check_diagrams=True)
        self.assertNotEqual(code, 0)
        self.assertTrue(any("证据清单" in problem for problem in result["problems"]), result)

        manifest = {"version": 2, "engine": "mermaid", "diagramType": "flowchart",
                    "claims": [{"statement": "A --> B", "artifactRef": "line:2",
                                "artifactQuote": "A --> B", "provenance": "EXTRACTED",
                                "evidence": [{"path": "Flow.txt", "line": 1, "quote": "A --> B"}]}]}
        for name in ("panorama", "flow"):
            (self.path.parent / name / "diagram.evidence.json").write_text(
                json.dumps(manifest), encoding="utf-8")
        code, result = self.run_validator("architecture", content, source, check_diagrams=True)
        self.assertEqual(code, 0, result)

    @unittest.skipUnless(shutil.which("mmdc"), "Mermaid CLI is unavailable")
    def test_strict_diagrams_accept_understand_arch_ir_delivery_bundle(self):
        source = self.path.parent / "source"
        source.mkdir()
        (source / "Flow.txt").write_text("A --> B\n", encoding="utf-8")
        bundle = self.path.parent / "bundle"
        views = {}
        content = self.unrated_architecture(self.document("订单系统架构总览", ARCHITECTURE_HEADINGS))
        content = content.replace("# 订单系统架构总览\n", "# 订单系统架构总览\n\n> 源代码版本：非Git仓库\n", 1)
        content = content.replace("已核对的内容。", "已核对的内容。来源：Flow.txt#L1")
        content = content.replace("## 9. 问题清单与改进建议",
                                  "来源：Flow.txt#L1\n\n## 9. 问题清单与改进建议")
        for number, view in ((1, "overview"), (2, "details/flow")):
            directory = bundle / view
            directory.mkdir(parents=True)
            (directory / "architecture.mmd").write_text("flowchart LR\n  A --> B\n", encoding="utf-8")
            (directory / "architecture.mermaid.svg").write_text(
                '<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
            views[view] = {"rendererChecks": {"mermaid": "pass"}, "artifacts": [
                f"{view}/architecture.mmd", f"{view}/architecture.mermaid.svg"]}
            heading = ARCHITECTURE_HEADINGS[number - 1]
            content = content.replace(
                f"## {heading}\n\n已核对的内容。来源：Flow.txt#L1",
                f"## {heading}\n\n![{view}](bundle/{view}/architecture.mermaid.svg)\n\n"
                f"[可编辑图源](bundle/{view}/architecture.mmd)\n\n来源：Flow.txt#L1",
            )
        (bundle / "manifest.json").write_text(json.dumps({
            "coverageCheck": "pass", "geometryCheck": "pass", "views": views,
        }), encoding="utf-8")
        code, result = self.run_validator("architecture", content, source, check_diagrams=True)
        self.assertEqual(code, 0, result)

        (bundle / "manifest.json").write_text("[]", encoding="utf-8")
        code, result = self.run_validator("architecture", content, source, check_diagrams=True)
        self.assertNotEqual(code, 0)
        self.assertTrue(any("IR 交付清单" in problem for problem in result["problems"]), result)

    def test_architecture_overview_rejects_score_without_source(self):
        content = self.document("订单系统架构总览", ARCHITECTURE_HEADINGS).replace(
            "## 8. 架构评估\n\n已核对的内容。",
            "## 8. 架构评估\n\n| 维度 | 评分（1-5） | 依据及来源 |\n|---|---|---|\n"
            "| 服务与模块边界 | 5 | 很好 |\n"
            "| 通信机制 | 待评估 | 缺少资料 |\n"
            "| 数据架构 | 待评估 | 缺少资料 |\n"
            "| 可观测性 | 待评估 | 缺少资料 |\n"
            "| 可扩展性 | 待评估 | 缺少资料 |"
        )
        code, result = self.run_validator("architecture", content)
        self.assertNotEqual(code, 0)
        self.assertTrue(any("评分" in problem for problem in result.get("problems", [])), result)

    def test_architecture_overview_rejects_invalid_score_and_missing_dimension(self):
        content = self.document("订单系统架构总览", ARCHITECTURE_HEADINGS).replace(
            "## 8. 架构评估\n\n已核对的内容。",
            "## 8. 架构评估\n\n| 维度 | 评分（1-5） | 依据及来源 |\n|---|---|---|\n"
            "| 服务与模块边界 | 6 | Service.java#L1 |\n"
            "| 通信机制 | 待评估 | 缺少资料 |\n"
            "| 数据架构 | 待评估 | 缺少资料 |\n"
            "| 可观测性 | 待评估 | 缺少资料 |"
        )
        code, result = self.run_validator("architecture", content)
        self.assertNotEqual(code, 0)
        self.assertTrue(any("评分" in problem for problem in result.get("problems", [])), result)

    def test_architecture_assessment_allows_separate_quality_scenario_table(self):
        content = self.unrated_architecture(self.document("订单系统架构总览", ARCHITECTURE_HEADINGS))
        content = content.replace("## 1. 系统全景\n\n已核对的内容。",
                                  "## 1. 系统全景\n\n```mermaid\nflowchart LR\n  A --> B\n```")
        content = content.replace("## 2. 核心流程\n\n已核对的内容。",
                                  "## 2. 核心流程\n\n```mermaid\nflowchart LR\n  A --> B\n```")
        content = content.replace("## 9. 问题清单与改进建议",
                                  "### 质量场景\n\n| 触发 | 预期结果 |\n|---|---|\n"
                                  "| 用户发起请求 | 返回结果 |\n\n## 9. 问题清单与改进建议")
        code, result = self.run_validator("architecture", content)
        self.assertEqual(code, 0, result)

    def test_rejects_missing_or_reordered_section(self):
        headings = list(FEATURE_HEADINGS)
        headings[2], headings[3] = headings[3], headings[2]
        code, result = self.run_validator("feature", self.document("商品退款", headings))
        self.assertNotEqual(code, 0)
        self.assertFalse(result["valid"])
        self.assertTrue(any("章节" in item for item in result["problems"]))

    def test_rejects_unfilled_template_and_empty_section(self):
        content = self.document("功能名称", FEATURE_HEADINGS)
        content = content.replace("## 2. 现状、约束与缺口\n\n已核对的内容。",
                                  "## 2. 现状、约束与缺口\n\n<!-- TEMPLATE: 填写现状 -->")
        code, result = self.run_validator("feature", content)
        self.assertNotEqual(code, 0)
        self.assertTrue(any("标题" in item for item in result["problems"]))
        self.assertTrue(any("模板提示" in item for item in result["problems"]))
        self.assertTrue(any("空章节" in item for item in result["problems"]))

    def test_rejects_empty_table(self):
        content = self.document("商品退款", FEATURE_HEADINGS).replace(
            "## 5. 改动清单\n\n已核对的内容。",
            "## 5. 改动清单\n\n| 位置 | 改动 |\n|---|---|",
        )
        code, result = self.run_validator("feature", content)
        self.assertNotEqual(code, 0)
        self.assertTrue(any("空表格" in item for item in result["problems"]))

    def test_strict_validation_checks_citations_and_source_revision(self):
        source = self.path.parent / "source"
        source.mkdir()
        (source / "Order.java").write_text("class Order {}\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(source)], check=True)
        subprocess.run(["git", "-C", str(source), "add", "Order.java"], check=True)
        subprocess.run(["git", "-C", str(source), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "init"], check=True)
        commit = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
        content = self.document("订单服务", PROJECT_HEADINGS).replace(
            "已核对的内容。", "已核对的内容。来源：Order.java#L1"
        ).replace("# 订单服务\n", f"# 订单服务\n\n> 源代码版本：{commit}\n", 1)
        code, result = self.run_validator("project", content, source)
        self.assertEqual(code, 0, result)
        broken = content.replace("Order.java#L1", "Order.java#L9", 1)
        code, result = self.run_validator("project", broken, source)
        self.assertNotEqual(code, 0)
        self.assertTrue(any("行号" in problem for problem in result["problems"]))
        code, result = self.run_validator("project", content.replace(commit, "0" * 40), source)
        self.assertNotEqual(code, 0)
        self.assertTrue(any("版本" in problem for problem in result["problems"]))

    def test_strict_validation_rejects_uncited_section(self):
        source = self.path.parent / "source"
        source.mkdir()
        content = self.document("订单服务", PROJECT_HEADINGS)
        code, result = self.run_validator("project", content, source)
        self.assertNotEqual(code, 0)
        self.assertTrue(any("来源" in problem for problem in result["problems"]))

    def test_strict_validation_accepts_external_prd_link(self):
        source = self.path.parent / "source"
        source.mkdir()
        content = self.document("订单服务", PROJECT_HEADINGS).replace(
            "已核对的内容。", "已核对的内容。[PRD](https://example.com/spec#L2)"
        ).replace("# 订单服务\n", "# 订单服务\n\n> 源代码版本：非Git仓库\n", 1)
        code, result = self.run_validator("project", content, source)
        self.assertEqual(code, 0, result)


if __name__ == "__main__":
    unittest.main()
