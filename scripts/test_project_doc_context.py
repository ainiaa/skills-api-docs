import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("project_doc_context.py")


class ProjectDocContextTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        source = self.root / "src"
        source.mkdir()
        (source / "OrderController.java").write_text("class OrderController {}\n", encoding="utf-8")
        (source / "RefundController.java").write_text("class RefundController {}\n", encoding="utf-8")

    def run_context(self, *args):
        result = subprocess.run([sys.executable, str(SCRIPT), "--source", str(self.root), *args],
                                capture_output=True, text=True, check=False)
        return result.returncode, json.loads(result.stdout)

    def test_focus_keeps_related_facts_and_reports_total(self):
        code, result = self.run_context("--focus", "Refund")
        self.assertEqual(code, 0, result)
        self.assertEqual(result["matchedFiles"], ["src/RefundController.java"])
        self.assertEqual(result["totalFiles"], 2)
        self.assertTrue(any(item["name"] == "RefundController" for item in result["symbols"]))
        self.assertFalse(any(item["name"] == "OrderController" for item in result["symbols"]))

    def test_fresh_graph_adds_related_domain_flow_but_stale_graph_does_not(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "src"], check=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "init"], check=True)
        commit = subprocess.check_output(["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True).strip()
        ua = self.root / ".ua"
        ua.mkdir()
        graph = {"project": {"gitCommitHash": commit}, "nodes": [
            {"id": "flow:refund", "type": "flow", "name": "Refund flow", "filePath": "src/RefundController.java"},
            {"id": "step:approve", "type": "step", "name": "Approve refund"}],
            "edges": [{"source": "flow:refund", "target": "step:approve", "type": "flow_step"}]}
        (ua / "domain-graph.json").write_text(json.dumps(graph), encoding="utf-8")
        (ua / "knowledge-graph.json").write_text(json.dumps({
            "project": {"gitCommitHash": commit},
            "nodes": [{"id": "file:refund", "type": "file", "name": "RefundController", "filePath": "src/RefundController.java"}],
            "edges": [],
            "layers": [{"id": "api", "name": "API", "nodeIds": ["file:refund"]}],
            "tour": [{"order": 1, "title": "Read refund entry", "nodeIds": ["file:refund"]}],
        }), encoding="utf-8")
        _, fresh = self.run_context("--focus", "Refund")
        self.assertEqual(len(fresh["domainNodes"]), 2)
        self.assertEqual(fresh["graphTour"][0]["title"], "Read refund entry")
        self.assertEqual(fresh["graphLayers"][0]["name"], "API")
        (self.root / "src" / "RefundController.java").write_text("class ChangedRefundController {}\n", encoding="utf-8")
        _, stale = self.run_context("--focus", "Refund")
        self.assertEqual(stale["domainNodes"], [])
        self.assertEqual(stale["graphTour"], [])
        self.assertTrue(any("stale" in warning for warning in stale["warnings"]))


if __name__ == "__main__":
    unittest.main()
