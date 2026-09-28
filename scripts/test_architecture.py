import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from architecture_ir import build_context, validate_architecture
from architecture_renderers import render_archify, render_drawio, render_mermaid, render_plantuml


class ArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        source = self.root / "src" / "OrderController.java"
        source.parent.mkdir()
        source.write_text(
            "@RestController\n"
            "class OrderController {\n"
            "  void createOrder() {}\n"
            "}\n",
            encoding="utf-8",
        )
        self.ir = {
            "version": 1,
            "summary": "订单服务提供创建订单能力。",
            "domains": [{
                "id": "orders", "name": "订单", "responsibility": "处理订单请求",
                "provenance": "INFERRED",
                "evidence": [{"path": "src/OrderController.java", "line": 2, "quote": "class OrderController"}],
                "capabilities": [{
                    "text": "创建订单", "provenance": "INFERRED",
                    "evidence": [{"path": "src/OrderController.java", "line": 3, "quote": "createOrder"}],
                }],
                "keyClasses": [{
                    "name": "OrderController", "provenance": "EXTRACTED",
                    "evidence": [{"path": "src/OrderController.java", "line": 2, "quote": "class OrderController"}],
                }],
                "tables": [],
            }],
            "externalSystems": [],
            "relations": [],
        }

    def test_context_keeps_all_files_and_optional_domain_graph(self):
        for index in range(21):
            (self.root / "src" / f"Extra{index}.java").write_text("class Extra {}\n", encoding="utf-8")
        ua = self.root / ".ua"
        ua.mkdir()
        (ua / "domain-graph.json").write_text(json.dumps({"nodes": [{"id": "domain:orders"}], "edges": []}))
        context = build_context(self.root)
        self.assertEqual(len(context["files"]), 22)
        self.assertEqual(context["domainGraph"]["nodes"][0]["id"], "domain:orders")
        self.assertEqual(context["stats"]["files"], 22)
        self.assertTrue(any("domain-graph.json" in warning for warning in context["warnings"]))

    def test_context_exposes_all_declarations_routes_and_config_keys(self):
        (self.root / "src" / "OrderController.java").write_text(
            '@RestController\n@RequestMapping("/orders")\nclass OrderController {}\n', encoding="utf-8")
        (self.root / "application.properties").write_text("orders.remote.url=https://example.invalid\n", encoding="utf-8")
        context = build_context(self.root)
        self.assertTrue(any(item["name"] == "OrderController" for item in context["symbols"]))
        self.assertTrue(any(item["value"] == "/orders" for item in context["routes"]))
        self.assertTrue(any(item["key"] == "orders.remote.url" for item in context["configKeys"]))

    def test_context_warns_when_source_differs_from_graph_commit(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "src/OrderController.java"], check=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "init"], check=True)
        commit = subprocess.check_output(["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True).strip()
        ua = self.root / ".ua"
        ua.mkdir()
        (ua / "domain-graph.json").write_text(json.dumps({"project": {"gitCommitHash": commit}, "nodes": []}))
        (self.root / "src" / "OrderController.java").write_text("class ChangedController {}\n", encoding="utf-8")
        context = build_context(self.root)
        self.assertTrue(any("working tree" in warning for warning in context["warnings"]), context["warnings"])

    def test_fresh_graph_must_contain_extracted_class(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "src/OrderController.java"], check=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "init"], check=True)
        commit = subprocess.check_output(["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True).strip()
        ua = self.root / ".ua"
        ua.mkdir()
        graph = {"project": {"gitCommitHash": commit}, "nodes": [], "edges": []}
        (ua / "knowledge-graph.json").write_text(json.dumps(graph))
        self.assertTrue(any("graph" in value for value in validate_architecture(self.ir, self.root)))
        graph["nodes"].append({"type": "class", "name": "OrderController", "filePath": "src/OrderController.java"})
        (ua / "knowledge-graph.json").write_text(json.dumps(graph))
        self.assertEqual(validate_architecture(self.ir, self.root), [])

    def test_codegraph_discovery_checks_class_location_when_indexed(self):
        (self.root / ".codegraph").mkdir()
        manifest = self.root / "fake-engine.json"
        manifest.write_text(json.dumps({"project_root": str(self.root), "files": [], "locate": {}}))
        with patch.dict(os.environ, API_SAVIOR_FAKE_ENGINE=str(manifest)):
            self.assertTrue(any("discovery" in value for value in validate_architecture(self.ir, self.root)))
            manifest.write_text(json.dumps({"project_root": str(self.root), "files": [], "locate": {
                "OrderController": [{"path": "src/OrderController.java", "line": 2, "kind": "class"}]}}))
            self.assertEqual(validate_architecture(self.ir, self.root), [])

    def test_valid_ir_renders_all_four_formats(self):
        self.assertEqual(validate_architecture(self.ir, self.root), [])
        self.assertIn("flowchart LR", render_mermaid(self.ir))
        self.assertIn("@startuml", render_plantuml(self.ir))
        self.assertIn("<mxfile", render_drawio(self.ir))
        archify = render_archify(self.ir)
        self.assertEqual(archify["schema_version"], 1)
        self.assertEqual(archify["components"][0]["id"], "orders")

    def test_renderer_escapes_user_labels_and_rejects_unsafe_ids(self):
        self.ir["domains"][0]["name"] = 'Orders & <invoices> "today"'
        self.assertEqual(ET.fromstring(render_drawio(self.ir)).tag, "mxfile")
        self.assertNotIn('<invoices>', render_mermaid(self.ir))
        self.ir["domains"][0]["id"] = "orders;drop"
        self.assertTrue(any("id" in problem for problem in validate_architecture(self.ir, self.root)))
        self.ir["domains"][0]["id"] = "orders-api"
        self.assertTrue(any("id" in problem for problem in validate_architecture(self.ir, self.root)))

    def test_rejects_missing_or_mismatched_evidence(self):
        self.ir["domains"][0]["capabilities"][0]["evidence"][0]["quote"] = "deleteOrder"
        problems = validate_architecture(self.ir, self.root)
        self.assertTrue(any("quote" in problem for problem in problems), problems)
        self.ir["domains"][0]["capabilities"][0]["evidence"][0]["path"] = "../outside.java"
        problems = validate_architecture(self.ir, self.root)
        self.assertTrue(any("outside" in problem or "path" in problem for problem in problems), problems)

    def test_rejects_false_class_and_relation(self):
        self.ir["domains"][0]["keyClasses"][0]["name"] = "GhostController"
        self.ir["relations"] = [{
            "from": "orders", "to": "missing", "label": "calls",
            "provenance": "INFERRED",
            "evidence": [{"path": "src/OrderController.java", "line": 3, "quote": "createOrder"}],
        }]
        problems = validate_architecture(self.ir, self.root)
        self.assertTrue(any("GhostController" in problem for problem in problems), problems)
        self.assertTrue(any("missing" in problem for problem in problems), problems)

    def test_rejects_class_reference_without_declaration_and_unverified_client(self):
        self.ir["domains"][0]["keyClasses"][0]["evidence"] = [
            {"path": "src/OrderController.java", "line": 3, "quote": "OrderController"}
        ]
        (self.root / "src" / "OrderController.java").write_text(
            "@RestController\nclass OrderController {\n  OrderController other;\n}\n", encoding="utf-8")
        self.ir["externalSystems"] = [{
            "name": "EBS", "kind": "Feign", "via": ["GhostClient"], "provenance": "INFERRED",
            "evidence": [{"path": "src/OrderController.java", "line": 3, "quote": "OrderController"}],
        }]
        problems = validate_architecture(self.ir, self.root)
        self.assertTrue(any("declaration" in problem for problem in problems), problems)
        self.assertTrue(any("GhostClient" in problem for problem in problems), problems)

    def test_external_domain_reference_is_validated_and_rendered(self):
        (self.root / "src" / "EbsClient.java").write_text("interface EbsClient {}\n", encoding="utf-8")
        self.ir["externalSystems"] = [{
            "name": "EBS", "kind": "Feign", "via": ["EbsClient"], "domain": "orders",
            "provenance": "INFERRED",
            "evidence": [{"path": "src/EbsClient.java", "line": 1, "quote": "interface EbsClient"}],
        }]
        self.assertEqual(validate_architecture(self.ir, self.root), [])
        self.assertIn("D_orders -.->", render_mermaid(self.ir))
        self.assertTrue(any(edge["to"] == "external_0" for edge in render_archify(self.ir)["connections"]))
        self.ir["externalSystems"][0]["domain"] = "missing"
        self.assertTrue(any("missing" in value for value in validate_architecture(self.ir, self.root)))

    def test_multiple_external_components_have_distinct_archify_positions(self):
        external = {"name": "EBS", "kind": "Feign", "domain": "orders"}
        self.ir["externalSystems"] = [external, dict(external, name="CRM")]
        components = [item for item in render_archify(self.ir)["components"] if item["type"] == "external"]
        self.assertNotEqual((components[0]["row"], components[0]["col"]),
                            (components[1]["row"], components[1]["col"]))

    def test_rejects_unanchored_capability_and_duplicate_domain(self):
        self.ir["domains"][0]["capabilities"][0]["evidence"] = []
        self.ir["domains"].append(dict(self.ir["domains"][0]))
        problems = validate_architecture(self.ir, self.root)
        self.assertTrue(any("evidence" in problem for problem in problems), problems)
        self.assertTrue(any("duplicate" in problem for problem in problems), problems)

    def test_semantic_claims_cannot_be_mislabeled_as_extracted(self):
        self.ir["domains"][0]["provenance"] = "EXTRACTED"
        self.ir["domains"][0]["capabilities"][0]["provenance"] = "EXTRACTED"
        problems = validate_architecture(self.ir, self.root)
        self.assertTrue(any("domain provenance" in problem for problem in problems), problems)
        self.assertTrue(any("创建订单" in problem for problem in problems), problems)

    def test_cli_rejects_invalid_ir_before_writing_artifacts(self):
        ir_path = self.root / "ir.json"
        output = self.root / "output"
        ir_path.write_text(json.dumps(self.ir), encoding="utf-8")
        cli = Path(__file__).with_name("generate_architecture.py")
        command = [sys.executable, str(cli), "render", "--source", str(self.root), "--ir", str(ir_path), "--output", str(output)]
        valid = subprocess.run(command, text=True, capture_output=True)
        self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
        self.assertTrue((output / "architecture.archify.json").is_file())
        self.ir["domains"][0]["keyClasses"][0]["name"] = "GhostController"
        ir_path.write_text(json.dumps(self.ir), encoding="utf-8")
        before = (output / "architecture.ir.json").read_text(encoding="utf-8")
        invalid = subprocess.run(command, text=True, capture_output=True)
        self.assertNotEqual(invalid.returncode, 0)
        self.assertEqual((output / "architecture.ir.json").read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
