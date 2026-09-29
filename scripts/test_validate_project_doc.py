import json
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


class ValidateProjectDocTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "document.md"

    def run_validator(self, kind, content, source=None):
        self.path.write_text(content, encoding="utf-8")
        process = subprocess.run(
            [sys.executable, str(VALIDATOR), "--kind", kind, "--file", str(self.path),
             *(["--source", str(source)] if source else [])],
            text=True, capture_output=True, check=False,
        )
        return process.returncode, json.loads(process.stdout)

    @staticmethod
    def document(title, headings):
        return "# " + title + "\n\n" + "\n\n".join(
            "## " + heading + "\n\n已核对的内容。" for heading in headings
        ) + "\n"

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
