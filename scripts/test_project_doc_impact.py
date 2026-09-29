import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("project_doc_impact.py")


class ProjectDocImpactTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "Order.java").write_text("class Order {}\n", encoding="utf-8")
        (self.root / "Refund.java").write_text("class Refund {}\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "Order.java", "Refund.java"], check=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "init"], check=True)
        self.commit = subprocess.check_output(["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True).strip()
        self.document = self.root / "project.md"
        self.document.write_text(
            f"# 服务\n\n> 源代码版本：{self.commit}\n\n"
            "## 1. 订单\n\n订单能力。来源：Order.java#L1\n\n"
            "## 2. 退款\n\n退款能力。来源：Refund.java#L1\n", encoding="utf-8")

    def run_impact(self, *args):
        result = subprocess.run([sys.executable, str(SCRIPT), "--source", str(self.root),
                                 "--file", str(self.document), *args],
                                capture_output=True, text=True, check=False)
        return result.returncode, json.loads(result.stdout)

    def test_reports_only_sections_citing_changed_file(self):
        (self.root / "Refund.java").write_text("class UpdatedRefund {}\n", encoding="utf-8")
        code, result = self.run_impact()
        self.assertEqual(code, 0, result)
        self.assertEqual(result["affectedSections"], ["2. 退款"])
        self.assertEqual(result["unmappedChangedFiles"], [])

    def test_reports_uncited_new_file_for_scope_review(self):
        (self.root / "NewFeature.java").write_text("class NewFeature {}\n", encoding="utf-8")
        code, result = self.run_impact()
        self.assertEqual(code, 0, result)
        self.assertEqual(result["affectedSections"], [])
        self.assertEqual(result["unmappedChangedFiles"], ["NewFeature.java"])
        self.assertTrue(result["needsScopeReview"])

    def test_reports_changes_committed_after_document_revision(self):
        (self.root / "Order.java").write_text("class UpdatedOrder {}\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "Order.java"], check=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "change"], check=True)
        code, result = self.run_impact()
        self.assertEqual(code, 0, result)
        self.assertEqual(result["affectedSections"], ["1. 订单"])

    def test_no_changes_preserves_document(self):
        before = self.document.read_text(encoding="utf-8")
        code, result = self.run_impact()
        self.assertEqual(code, 0, result)
        self.assertEqual(result["changedFiles"], [])
        self.assertEqual(self.document.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
