import json
import copy
import os
import re
import shutil
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

    def test_context_recognizes_multiline_mapping_with_path_argument(self):
        (self.root / "src" / "OrderController.java").write_text(
            '@RestController\nclass OrderController {\n  @GetMapping(\n'
            '    path = "/orders"\n  )\n  void list() {}\n}\n', encoding="utf-8")
        context = build_context(self.root)
        self.assertIn({"value": "/orders", "path": "src/OrderController.java", "line": 3},
                      context["routes"])

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
        self.assertEqual(archify["components"][0]["id"], "domain_orders")

    def test_generated_node_ids_remain_unique_when_domain_ids_resemble_generated_ids(self):
        (self.root / "tables.sql").write_text("CREATE TABLE alpha\n", encoding="utf-8")
        self.ir["domains"][0]["tables"] = [{
            "name": "alpha", "provenance": "EXTRACTED",
            "evidence": [{"path": "tables.sql", "line": 1, "quote": "alpha"}],
        }]
        for domain_id in ("orders_T0", "orders_table_0", "external_0"):
            domain = copy.deepcopy(self.ir["domains"][0])
            domain.update(id=domain_id, name=domain_id, tables=[])
            self.ir["domains"].append(domain)
        (self.root / "src" / "EbsClient.java").write_text("interface EbsClient {}\n", encoding="utf-8")
        self.ir["externalSystems"] = [{
            "name": "EBS", "kind": "Feign", "via": ["EbsClient"], "domain": "orders",
            "provenance": "INFERRED",
            "evidence": [{"path": "src/EbsClient.java", "line": 1, "quote": "interface EbsClient"}],
        }]
        self.assertEqual(validate_architecture(self.ir, self.root), [])
        cells = [cell.attrib["id"] for cell in ET.fromstring(render_drawio(self.ir)).iter("mxCell")]
        self.assertEqual(len(cells), len(set(cells)))
        mermaid_ids = re.findall(r'^\s+([DTE][A-Za-z0-9_]*)\[', render_mermaid(self.ir), re.MULTILINE)
        plantuml_ids = re.findall(r'\bas ([DTE][A-Za-z0-9_]*)$', render_plantuml(self.ir), re.MULTILINE)
        for ids in (mermaid_ids, plantuml_ids):
            self.assertEqual(len(ids), len(set(ids)))
            self.assertIn("D_orders_T0", ids)
            self.assertIn("T_orders_0", ids)
        components = render_archify(self.ir)["components"]
        ids = [component["id"] for component in components]
        self.assertEqual(len(ids), len(set(ids)))

    def test_archify_places_each_table_in_a_distinct_grid_cell(self):
        (self.root / "tables.sql").write_text("CREATE TABLE alpha\nCREATE TABLE beta\n", encoding="utf-8")
        self.ir["domains"][0]["tables"] = [
            {"name": name, "provenance": "EXTRACTED",
             "evidence": [{"path": "tables.sql", "line": line, "quote": name}]}
            for line, name in enumerate(("alpha", "beta"), 1)
        ]
        self.assertEqual(validate_architecture(self.ir, self.root), [])
        components = render_archify(self.ir)["components"]
        positions = [(component["row"], component["col"]) for component in components]
        self.assertEqual(len(positions), len(set(positions)))

    def test_validation_rejects_renderer_unsafe_values_without_raising(self):
        self.ir["domains"][0]["name"] = "bad\x00label"
        self.assertTrue(any("name" in problem for problem in validate_architecture(self.ir, self.root)))
        self.ir["domains"][0]["name"] = "orders"
        (self.root / "src" / "EbsClient.java").write_text("interface EbsClient {}\n", encoding="utf-8")
        self.ir["externalSystems"] = [{
            "name": "EBS", "kind": None, "via": ["EbsClient"], "domain": "orders",
            "provenance": "INFERRED",
            "evidence": [{"path": "src/EbsClient.java", "line": 1, "quote": "interface EbsClient"}],
        }]
        self.assertTrue(any("kind" in problem for problem in validate_architecture(self.ir, self.root)))
        self.ir["externalSystems"][0]["kind"] = "Feign"
        self.ir["externalSystems"][0]["domain"] = []
        self.assertTrue(any("domain" in problem for problem in validate_architecture(self.ir, self.root)))
        self.ir["externalSystems"] = []
        self.ir["relations"] = [{"from": [], "to": "orders", "label": "calls", "provenance": "INFERRED",
                                "evidence": [{"path": "src/OrderController.java", "line": 3, "quote": "createOrder"}]}]
        self.assertTrue(any("from" in problem for problem in validate_architecture(self.ir, self.root)))

    def test_validation_reports_malformed_evidence_path(self):
        self.ir["domains"][0]["evidence"][0]["path"] = "\x00"
        try:
            problems = validate_architecture(self.ir, self.root)
        except ValueError as error:
            self.fail(f"validation raised instead of reporting the path: {error}")
        self.assertTrue(any("path" in problem for problem in problems), problems)

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
        command = [sys.executable, str(cli), "render", "--source", str(self.root), "--ir", str(ir_path),
                   "--output", str(output), "--format", "archify"]
        valid = subprocess.run(command, text=True, capture_output=True)
        self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
        self.assertTrue((output / "architecture.archify.json").is_file())
        self.ir["domains"][0]["keyClasses"][0]["name"] = "GhostController"
        ir_path.write_text(json.dumps(self.ir), encoding="utf-8")
        before = (output / "architecture.ir.json").read_text(encoding="utf-8")
        invalid = subprocess.run(command, text=True, capture_output=True)
        self.assertNotEqual(invalid.returncode, 0)
        self.assertEqual((output / "architecture.ir.json").read_text(encoding="utf-8"), before)

    def test_render_delivers_only_requested_native_format_and_svg_is_opt_in(self):
        ir_path = self.root / "ir.json"
        ir_path.write_text(json.dumps(self.ir), encoding="utf-8")
        output = self.root / "output"
        engine = self.root / "engine"
        engine.write_text(
            '#!/usr/bin/env python3\n'
            'import pathlib, sys\n'
            'args = sys.argv[1:]\n'
            'target = pathlib.Path(args[args.index("-o" if "-i" in args else "--output") + 1])\n'
            'target.write_text("<svg xmlns=\\"http://www.w3.org/2000/svg\\"><text>diagram</text></svg>")\n',
            encoding="utf-8")
        engine.chmod(0o755)
        base = [sys.executable, str(Path(__file__).with_name("generate_architecture.py")),
                "render", "--source", str(self.root), "--ir", str(ir_path), "--output", str(output)]
        missing_format = subprocess.run(base, text=True, capture_output=True)
        self.assertNotEqual(missing_format.returncode, 0)
        missing_svg_engine = subprocess.run([*base, "--format", "mermaid", "--svg-for", "mermaid",
                                             "--mermaid-cli", str(self.root / "missing-mmdc")],
                                            text=True, capture_output=True)
        self.assertNotEqual(missing_svg_engine.returncode, 0)
        mermaid = subprocess.run([*base, "--format", "mermaid", "--mermaid-cli", str(engine)],
                                 text=True, capture_output=True)
        self.assertEqual(mermaid.returncode, 0, mermaid.stdout + mermaid.stderr)
        self.assertEqual(json.loads(mermaid.stdout)["rendererChecks"], {"mermaid": "pass"})
        self.assertEqual({path.name for path in output.iterdir()},
                         {"architecture.ir.json", "architecture.mmd"})
        drawio = subprocess.run([*base, "--format", "drawio", "--drawio-cli", str(engine)],
                                text=True, capture_output=True)
        self.assertEqual(drawio.returncode, 0, drawio.stdout + drawio.stderr)
        self.assertEqual({path.name for path in output.iterdir()},
                         {"architecture.ir.json", "architecture.drawio"})
        svg = subprocess.run([*base, "--format", "mermaid", "--svg-for", "mermaid",
                              "--mermaid-cli", str(engine)],
                             text=True, capture_output=True)
        self.assertEqual(svg.returncode, 0, svg.stdout + svg.stderr)
        self.assertEqual({path.name for path in output.iterdir()},
                         {"architecture.ir.json", "architecture.mmd", "architecture.mermaid.svg"})
        mixed = subprocess.run([*base, "--format", "mermaid", "--format", "drawio",
                                "--svg-for", "mermaid", "--mermaid-cli", str(engine),
                                "--drawio-cli", str(engine)], text=True, capture_output=True)
        self.assertEqual(mixed.returncode, 0, mixed.stdout + mixed.stderr)
        self.assertEqual({path.name for path in output.iterdir()},
                         {"architecture.ir.json", "architecture.mmd", "architecture.drawio",
                          "architecture.mermaid.svg"})

    def test_archify_failure_does_not_leave_stale_html(self):
        ir_path = self.root / "ir.json"
        output = self.root / "output"
        ir_path.write_text(json.dumps(self.ir), encoding="utf-8")
        archify = self.root / "archify"
        archify.write_text(
            '#!/bin/sh\n'
            'if [ "$1" != deliver ]; then echo "expected deliver" >&2; exit 2; fi\n'
            'if [ "$FAIL_ARCHIFY" = 1 ]; then echo rejected >&2; exit 1; fi\n'
            'printf first-render > "$4"\n'
            'if [ "$BAD_RECEIPT" = 1 ]; then printf "{\\"ok\\":true,\\"command\\":\\"deliver\\",\\"validation\\":[]}"; exit 0; fi\n'
            'printf "{\\"ok\\":true,\\"command\\":\\"deliver\\",\\"validation\\":{\\"checksPassed\\":9,\\"checkCount\\":9,\\"compositionProfile\\":\\"showcase\\",\\"compositionStatus\\":\\"pass\\",\\"errors\\":0,\\"warnings\\":0}}"\n',
            encoding="utf-8")
        archify.chmod(0o755)
        command = [sys.executable, str(Path(__file__).with_name("generate_architecture.py")),
                   "render", "--source", str(self.root), "--ir", str(ir_path), "--output", str(output),
                   "--format", "archify", "--archify-cli", str(archify)]
        environment = dict(os.environ, PATH=str(self.root) + os.pathsep + os.environ["PATH"])
        first = subprocess.run(command, text=True, capture_output=True, env=environment)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertTrue(json.loads(first.stdout).get("archifyRendered"))
        self.assertTrue((output / "architecture.archify.html").is_file())
        self.ir["summary"] = "updated"
        ir_path.write_text(json.dumps(self.ir), encoding="utf-8")
        failed = subprocess.run(command, text=True, capture_output=True,
                                env=dict(environment, FAIL_ARCHIFY="1"))
        self.assertNotEqual(failed.returncode, 0)
        self.assertFalse(json.loads(failed.stdout).get("archifyRendered", True))
        self.assertFalse((output / "architecture.archify.html").exists())
        self.assertEqual(json.loads((output / "architecture.ir.json").read_text(encoding="utf-8"))["summary"], "updated")
        malformed = subprocess.run(command, text=True, capture_output=True,
                                   env=dict(environment, BAD_RECEIPT="1"))
        self.assertNotEqual(malformed.returncode, 0)
        self.assertFalse((output / "architecture.archify.html").exists())

    def test_official_renderer_gate_requires_svg_and_cleans_failed_output(self):
        ir_path = self.root / "ir.json"
        ir_path.write_text(json.dumps(self.ir), encoding="utf-8")
        output = self.root / "output"
        engine = self.root / "engine"
        engine.write_text(
            '#!/usr/bin/env python3\n'
            'import os, pathlib, sys\n'
            'args = sys.argv[1:]\n'
            'kind = "mermaid" if "-i" in args else ("drawio" if "--export" in args else "plantuml")\n'
            'if os.environ.get("FAIL_RENDERER") == kind: sys.exit(2)\n'
            'if kind == "plantuml" and "-checkonly" in args: sys.exit(0)\n'
            'if kind == "plantuml": target = pathlib.Path(args[args.index("-o") + 1]) / (pathlib.Path(args[-1]).stem + ".svg")\n'
            'else: target = pathlib.Path(args[args.index("-o" if kind == "mermaid" else "--output") + 1])\n'
            'target.write_text("<svg xmlns=\\"http://www.w3.org/2000/svg\\"><text>diagram</text></svg>")\n',
            encoding="utf-8")
        engine.chmod(0o755)
        command = [sys.executable, str(Path(__file__).with_name("generate_architecture.py")),
                   "render", "--source", str(self.root), "--ir", str(ir_path), "--output", str(output),
                   "--format", "mermaid", "--format", "plantuml", "--format", "drawio",
                   "--svg-for", "mermaid", "--svg-for", "plantuml", "--svg-for", "drawio",
                   "--mermaid-cli", str(engine), "--plantuml-cli", str(engine), "--drawio-cli", str(engine)]
        success = subprocess.run(command, text=True, capture_output=True)
        self.assertEqual(success.returncode, 0, success.stdout + success.stderr)
        result = json.loads(success.stdout)
        self.assertEqual(result["rendererChecks"], {"mermaid": "pass", "plantuml": "pass", "drawio": "pass"})
        for name in ("mermaid", "plantuml", "drawio"):
            self.assertEqual(ET.parse(output / f"architecture.{name}.svg").getroot().tag,
                             "{http://www.w3.org/2000/svg}svg")
        failed = subprocess.run(command, text=True, capture_output=True,
                                env=dict(os.environ, FAIL_RENDERER="plantuml"))
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(json.loads(failed.stdout)["rendererChecks"]["plantuml"], "fail")
        self.assertFalse((output / "architecture.plantuml.svg").exists())
        self.assertTrue((output / "architecture.mermaid.svg").exists())

    def test_renderer_gate_rejects_missing_cli_and_invalid_svg(self):
        ir_path = self.root / "ir.json"
        ir_path.write_text(json.dumps(self.ir), encoding="utf-8")
        output = self.root / "output"
        base = [sys.executable, str(Path(__file__).with_name("generate_architecture.py")),
                "render", "--source", str(self.root), "--ir", str(ir_path), "--output", str(output),
                "--format", "mermaid", "--svg-for", "mermaid"]
        missing = subprocess.run([*base, "--mermaid-cli", str(self.root / "absent")],
                                 text=True, capture_output=True)
        self.assertNotEqual(missing.returncode, 0)
        self.assertEqual(json.loads(missing.stdout)["rendererChecks"]["mermaid"], "fail")
        engine = self.root / "bad-engine"
        engine.write_text('#!/bin/sh\nprintf "not svg" > "$4"\n', encoding="utf-8")
        engine.chmod(0o755)
        invalid = subprocess.run([*base, "--mermaid-cli", str(engine)], text=True, capture_output=True)
        self.assertNotEqual(invalid.returncode, 0)
        self.assertFalse((output / "architecture.mermaid.svg").exists())

    def test_requested_raster_and_pdf_exports_are_checked_and_cleaned(self):
        ir_path = self.root / "ir.json"
        ir_path.write_text(json.dumps(self.ir), encoding="utf-8")
        output = self.root / "output"
        engine = self.root / "format-engine"
        engine.write_text(
            '#!/usr/bin/env python3\n'
            'import os, pathlib, sys\n'
            'args = sys.argv[1:]\n'
            'if "-checkonly" in args: sys.exit(0)\n'
            'kind = "mermaid" if "-i" in args else ("drawio" if "--export" in args else "plantuml")\n'
            'if kind == "plantuml":\n'
            '    fmt = args[args.index("--format") + 1]\n'
            '    target = pathlib.Path(args[args.index("--output-dir") + 1]) / (pathlib.Path(args[-1]).stem + "." + fmt)\n'
            'else:\n'
            '    target = pathlib.Path(args[args.index("-o" if kind == "mermaid" else "--output") + 1])\n'
            '    fmt = target.suffix[1:]\n'
            'if os.environ.get("FAIL_FORMAT") == kind + ":" + fmt: sys.exit(3)\n'
            'if os.environ.get("BAD_FORMAT") == kind + ":" + fmt: target.write_bytes(b"bad"); sys.exit(0)\n'
            'data = {"svg": b"<svg xmlns=\\"http://www.w3.org/2000/svg\\"><text>diagram</text></svg>",\n'
            '        "png": b"\\x89PNG\\r\\n\\x1a\\n" + b"\\0\\0\\0\\rIHDR" + b"\\0\\0\\0\\x01\\0\\0\\0\\x01",\n'
            '        "jpg": b"\\xff\\xd8\\xff\\xe0" + b"fake" + b"\\xff\\xd9",\n'
            '        "pdf": b"%PDF-1.4\\n" + b"fake" + b"\\n%%EOF"}\n'
            'target.write_bytes(data[fmt])\n', encoding="utf-8")
        engine.chmod(0o755)
        base = [sys.executable, str(Path(__file__).with_name("generate_architecture.py")),
                "render", "--source", str(self.root), "--ir", str(ir_path), "--output", str(output)]
        requested = [*base, "--format", "mermaid", "--format", "plantuml", "--format", "drawio",
                     "--export-for", "mermaid:png", "--export-for", "mermaid:pdf",
                     "--export-for", "plantuml:png", "--export-for", "plantuml:pdf",
                     "--export-for", "drawio:png", "--export-for", "drawio:jpg",
                     "--export-for", "drawio:pdf", "--export-for", "drawio:svg",
                     "--mermaid-cli", str(engine), "--plantuml-cli", str(engine),
                     "--drawio-cli", str(engine)]
        rendered = subprocess.run(requested, text=True, capture_output=True)
        self.assertEqual(rendered.returncode, 0, rendered.stdout + rendered.stderr)
        result = json.loads(rendered.stdout)
        self.assertEqual(result["rendererChecks"],
                         {"mermaid": "pass", "plantuml": "pass", "drawio": "pass"})
        for kind, fmt in (("mermaid", "png"), ("mermaid", "pdf"),
                          ("plantuml", "png"), ("plantuml", "pdf"),
                          ("drawio", "png"), ("drawio", "jpg"), ("drawio", "pdf"),
                          ("drawio", "svg")):
            target = output / f"architecture.{kind}.{fmt}"
            self.assertTrue(target.is_file(), target)
            self.assertIn(str(target.resolve()), result["artifacts"])
        failed = subprocess.run(requested, text=True, capture_output=True,
                                env=dict(os.environ, FAIL_FORMAT="drawio:jpg"))
        self.assertNotEqual(failed.returncode, 0)
        self.assertFalse((output / "architecture.drawio.jpg").exists())
        self.assertNotIn(str((output / "architecture.drawio.jpg").resolve()),
                         json.loads(failed.stdout)["artifacts"])
        invalid = subprocess.run(requested, text=True, capture_output=True,
                                 env=dict(os.environ, BAD_FORMAT="mermaid:pdf"))
        self.assertNotEqual(invalid.returncode, 0)
        self.assertFalse((output / "architecture.mermaid.pdf").exists())
        self.assertEqual(json.loads(invalid.stdout)["rendererChecks"]["mermaid"], "fail")
        unavailable = subprocess.run([*base, "--format", "mermaid", "--export-for", "mermaid:png",
                                      "--mermaid-cli", str(self.root / "missing")], text=True, capture_output=True)
        self.assertNotEqual(unavailable.returncode, 0)
        self.assertFalse((output / "architecture.mermaid.png").exists())
        shrunk = subprocess.run([*base, "--format", "mermaid", "--mermaid-cli", str(engine)],
                                text=True, capture_output=True)
        self.assertEqual(shrunk.returncode, 0, shrunk.stdout + shrunk.stderr)
        self.assertEqual({path.name for path in output.iterdir()},
                         {"architecture.ir.json", "architecture.mmd"})

    def test_export_requests_reject_unsupported_or_unselected_pairs(self):
        ir_path = self.root / "ir.json"
        ir_path.write_text(json.dumps(self.ir), encoding="utf-8")
        base = [sys.executable, str(Path(__file__).with_name("generate_architecture.py")),
                "render", "--source", str(self.root), "--ir", str(ir_path),
                "--output", str(self.root / "output"), "--format", "mermaid"]
        for export in ("mermaid:jpg", "plantuml:png", "mermaid:gif", "archify:gif", "bad", "mermaid:png:jpg"):
            with self.subTest(export=export):
                rejected = subprocess.run([*base, "--export-for", export], text=True, capture_output=True)
                self.assertNotEqual(rejected.returncode, 0)
                self.assertFalse((self.root / "output").exists())
        missing_archify = subprocess.run([*base[:-2], "--format", "archify", "--export-for", "archify:png",
                                          "--archify-cli", str(self.root / "missing-archify")],
                                         text=True, capture_output=True)
        self.assertNotEqual(missing_archify.returncode, 0)
        self.assertFalse((self.root / "output" / "architecture.archify.png").exists())

    @unittest.skipUnless(all(os.environ.get(name) for name in
                             ("MERMAID_OFFICIAL_CLI", "PLANTUML_OFFICIAL_CLI", "DRAWIO_OFFICIAL_CLI")),
                         "official Mermaid, PlantUML, and draw.io CLIs are not configured")
    def test_official_diagram_engines_accept_generated_outputs(self):
        (self.root / "tables.sql").write_text("CREATE TABLE orders\n", encoding="utf-8")
        self.ir["domains"][0]["name"] = "A & B"
        self.ir["domains"][0]["tables"] = [{
            "name": "orders", "provenance": "EXTRACTED",
            "evidence": [{"path": "tables.sql", "line": 1, "quote": "orders"}],
        }]
        billing = copy.deepcopy(self.ir["domains"][0])
        billing.update(id="billing", name="Billing", tables=[])
        self.ir["domains"].append(billing)
        self.ir["relations"] = [{
            "from": "orders", "to": "billing", "label": "charges", "provenance": "INFERRED",
            "evidence": [{"path": "src/OrderController.java", "line": 3, "quote": "createOrder"}],
        }]
        (self.root / "src" / "EbsClient.java").write_text("interface EbsClient {}\n", encoding="utf-8")
        self.ir["externalSystems"] = [{
            "name": "ERP", "kind": "REST", "via": ["EbsClient"], "domain": "orders",
            "provenance": "INFERRED",
            "evidence": [{"path": "src/EbsClient.java", "line": 1, "quote": "EbsClient"}],
        }]
        self.assertEqual(validate_architecture(self.ir, self.root), [])
        ir_path = self.root / "ir.json"
        ir_path.write_text(json.dumps(self.ir), encoding="utf-8")
        output = self.root / "output"
        command = [sys.executable, str(Path(__file__).with_name("generate_architecture.py")),
                   "render", "--source", str(self.root), "--ir", str(ir_path), "--output", str(output)]
        for kind in ("mermaid", "plantuml", "drawio"):
            command.extend(["--format", kind, "--svg-for", kind,
                            f"--{kind}-cli", os.environ[f"{kind.upper()}_OFFICIAL_CLI"]])
            for fmt in (("png", "pdf") if kind != "drawio" else ("png", "jpg", "pdf")):
                command.extend(["--export-for", f"{kind}:{fmt}"])
        rendered = subprocess.run(command, text=True, capture_output=True, timeout=360)
        self.assertEqual(rendered.returncode, 0, rendered.stdout + rendered.stderr)
        self.assertEqual(json.loads(rendered.stdout)["rendererChecks"],
                         {"mermaid": "pass", "plantuml": "pass", "drawio": "pass"})
        for kind in ("mermaid", "plantuml", "drawio"):
            svg = output / f"architecture.{kind}.svg"
            self.assertGreater(svg.stat().st_size, 100)
            self.assertEqual(ET.parse(svg).getroot().tag, "{http://www.w3.org/2000/svg}svg")
            for fmt in (("png", "pdf") if kind != "drawio" else ("png", "jpg", "pdf")):
                artifact = output / f"architecture.{kind}.{fmt}"
                data = artifact.read_bytes()
                self.assertGreater(len(data), 100)
                self.assertTrue(data.startswith({"png": b"\x89PNG\r\n\x1a\n", "jpg": b"\xff\xd8\xff",
                                                "pdf": b"%PDF-"}[fmt]), artifact)
        pdf_only = subprocess.run([sys.executable, str(Path(__file__).with_name("generate_architecture.py")),
                                   "render", "--source", str(self.root), "--ir", str(ir_path),
                                   "--output", str(output), "--format", "plantuml",
                                   "--export-for", "plantuml:pdf", "--plantuml-cli",
                                   os.environ["PLANTUML_OFFICIAL_CLI"]],
                                  text=True, capture_output=True, timeout=120)
        self.assertEqual(pdf_only.returncode, 0, pdf_only.stdout + pdf_only.stderr)
        self.assertEqual({path.name for path in output.iterdir()},
                         {"architecture.ir.json", "architecture.puml", "architecture.plantuml.pdf"})

    @unittest.skipUnless(os.environ.get("ARCHIFY_OFFICIAL_CLI"), "official Archify CLI is not configured")
    def test_official_archify_validates_and_checks_adapter_output(self):
        (self.root / "tables.sql").write_text("CREATE TABLE orders\nCREATE TABLE order_items\n", encoding="utf-8")
        self.ir["summary"] = "Order system"
        self.ir["domains"][0]["name"] = "Orders"
        self.ir["domains"][0]["capabilities"][0]["text"] = "Create orders"
        self.ir["domains"][0]["tables"] = [
            {"name": name, "provenance": "EXTRACTED",
             "evidence": [{"path": "tables.sql", "line": line, "quote": name}]}
            for line, name in enumerate(("orders", "order_items"), 1)
        ]
        billing = copy.deepcopy(self.ir["domains"][0])
        billing.update(id="billing", name="Billing", tables=[])
        self.ir["domains"].append(billing)
        (self.root / "src" / "EbsClient.java").write_text("interface EbsClient {}\n", encoding="utf-8")
        self.ir["externalSystems"] = [{
            "name": "ERP", "kind": "REST", "via": ["EbsClient"], "domain": "orders",
            "provenance": "INFERRED",
            "evidence": [{"path": "src/EbsClient.java", "line": 1, "quote": "interface EbsClient"}],
        }]
        self.ir["relations"] = [{
            "from": "orders", "to": "billing", "label": "charge", "provenance": "INFERRED",
            "evidence": [{"path": "src/OrderController.java", "line": 3, "quote": "createOrder"}],
        }]
        ir_path = self.root / "ir.json"
        ir_path.write_text(json.dumps(self.ir), encoding="utf-8")
        output = self.root / "output"
        archify = os.environ["ARCHIFY_OFFICIAL_CLI"]
        command = [sys.executable, str(Path(__file__).with_name("generate_architecture.py")),
                   "render", "--source", str(self.root), "--ir", str(ir_path), "--output", str(output),
                   "--format", "archify", "--archify-cli", archify]
        rendered = subprocess.run(command, text=True, capture_output=True)
        self.assertEqual(rendered.returncode, 0, rendered.stdout + rendered.stderr)
        result = json.loads(rendered.stdout)
        self.assertTrue(result["archifyRendered"])
        self.assertEqual(result["archifyReceipt"]["validation"]["compositionStatus"], "pass")
        self.assertEqual(result["archifyReceipt"]["validation"]["compositionProfile"], "showcase")
        specification = output / "architecture.archify.json"
        html = output / "architecture.archify.html"
        for args in (("validate", "architecture", str(specification), "--quality", "showcase", "--json"),
                     ("check", str(html))):
            checked = subprocess.run([archify, *args], text=True, capture_output=True)
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            self.assertTrue(json.loads(checked.stdout)["ok"])
        chrome = (os.environ.get("ARCHIFY_CHROME") or
                  ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" if sys.platform == "darwin" else
                   shutil.which("google-chrome") or shutil.which("chromium")))
        if chrome and Path(chrome).is_file():
            requested = [*command]
            for fmt in ("svg", "png", "jpg", "webp", "pdf", "webm"):
                requested.extend(["--export-for", f"archify:{fmt}"])
            exported = subprocess.run(requested, text=True, capture_output=True, timeout=180)
            self.assertEqual(exported.returncode, 0, exported.stdout + exported.stderr)
            receipt = json.loads(exported.stdout)
            self.assertEqual(json.loads(specification.read_text(encoding="utf-8"))["meta"]["animation"], "trace")
            for fmt, signature in (("png", b"\x89PNG\r\n\x1a\n"), ("jpg", b"\xff\xd8\xff"),
                                   ("webp", b"RIFF"), ("pdf", b"%PDF-"),
                                   ("webm", b"\x1a\x45\xdf\xa3")):
                artifact = output / f"architecture.archify.{fmt}"
                self.assertTrue(artifact.is_file(), artifact)
                self.assertGreater(artifact.stat().st_size, 100)
                self.assertTrue(artifact.read_bytes().startswith(signature), artifact)
                self.assertIn(str(artifact.resolve()), receipt["artifacts"])
            svg = output / "architecture.archify.svg"
            self.assertEqual(ET.parse(svg).getroot().tag, "{http://www.w3.org/2000/svg}svg")
            no_browser = subprocess.run(requested, text=True, capture_output=True, timeout=30,
                                        env=dict(os.environ, ARCHIFY_CHROME=str(self.root / "absent-chrome")))
            self.assertNotEqual(no_browser.returncode, 0)
            self.assertIn("Chrome/Chromium", json.loads(no_browser.stdout)["problems"][0])
            self.assertFalse((output / "architecture.archify.png").exists())
            self.assertTrue(html.is_file())
            native_only = subprocess.run(command, text=True, capture_output=True, timeout=30)
            self.assertEqual(native_only.returncode, 0, native_only.stdout + native_only.stderr)
            self.assertFalse((output / "architecture.archify.webp").exists())
            pdf_only = subprocess.run([*command, "--export-for", "archify:pdf"],
                                      text=True, capture_output=True, timeout=60)
            self.assertEqual(pdf_only.returncode, 0, pdf_only.stdout + pdf_only.stderr)
            self.assertTrue((output / "architecture.archify.pdf").read_bytes().startswith(b"%PDF-"))
            self.assertNotIn("animation", json.loads(specification.read_text(encoding="utf-8"))["meta"])


if __name__ == "__main__":
    unittest.main()
