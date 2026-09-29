"""Acceptance tests for official native diagram sources outside typed IR v2."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("render_native_diagram.py")
ARCHIFY_CLI = os.environ.get("ARCHIFY_OFFICIAL_CLI") or shutil.which("archify")
ARCHIFY_EXAMPLES = Path(ARCHIFY_CLI).resolve().parent.parent / "examples" if ARCHIFY_CLI else None


class NativeDiagramTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / "out"

    def tearDown(self):
        self.temp.cleanup()

    def render(self, engine, source, *extra):
        return subprocess.run([sys.executable, str(SCRIPT), "--engine", engine,
                               "--input", str(source), "--output", str(self.output), *extra],
                              capture_output=True, text=True)

    def source_backed(self, *, engine="mermaid", diagram_type="class", artifact_quote="class Asset",
                      quote="class Asset", provenance="EXTRACTED", path="Asset.java", line=1):
        source_root = self.root / "source"
        source_root.mkdir(exist_ok=True)
        (source_root / "Asset.java").write_text("class Asset {}\n", encoding="utf-8")
        source = self.root / "classes.mmd"
        source.write_text("classDiagram\n  class Asset\n", encoding="utf-8")
        manifest = self.root / "evidence.json"
        manifest.write_text(json.dumps({"version": 1, "engine": engine,
                                        "diagramType": diagram_type,
                                        "claims": [{"statement": "Asset exists",
                                                    "artifactQuote": artifact_quote,
                                                    "provenance": provenance,
                                                    "evidence": [{"path": path, "line": line,
                                                                  "quote": quote}]}]}), encoding="utf-8")
        return source, source_root, manifest

    def test_source_repo_requires_evidence_manifest(self):
        source, source_root, _ = self.source_backed()
        result = self.render("mermaid", source, "--source-repo", str(source_root))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--evidence", result.stdout + result.stderr)
        self.assertFalse(self.output.exists())

    def test_evidence_manifest_requires_source_repo(self):
        source, _, manifest = self.source_backed()
        result = self.render("mermaid", source, "--evidence", str(manifest))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--source-repo", result.stdout + result.stderr)
        self.assertFalse(self.output.exists())

    def test_rejects_source_claim_without_matching_code_quote(self):
        source, source_root, manifest = self.source_backed(quote="class Missing")
        result = self.render("mermaid", source, "--source-repo", str(source_root),
                             "--evidence", str(manifest))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("quote does not occur", result.stdout + result.stderr)
        self.assertFalse(self.output.exists())

    def test_rejects_source_claim_without_matching_diagram_text(self):
        source, source_root, manifest = self.source_backed(artifact_quote="class Missing")
        result = self.render("mermaid", source, "--source-repo", str(source_root),
                             "--evidence", str(manifest))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("artifactQuote", result.stdout + result.stderr)
        self.assertFalse(self.output.exists())

    def test_v2_manifest_rejects_unclaimed_native_statement(self):
        source, source_root, manifest = self.source_backed()
        source.write_text("classDiagram\n  class Asset\n  class Ledger\n", encoding="utf-8")
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["version"] = 2
        payload["claims"][0]["artifactRef"] = "line:2"
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        result = self.render("mermaid", source, "--source-repo", str(source_root),
                             "--evidence", str(manifest))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("line:3", result.stdout + result.stderr)
        self.assertFalse(self.output.exists())

    def test_v2_manifest_rejects_nonliteral_extracted_statement(self):
        source, source_root, manifest = self.source_backed()
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["version"] = 2
        payload["claims"][0]["artifactRef"] = "line:2"
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        result = self.render("mermaid", source, "--source-repo", str(source_root),
                             "--evidence", str(manifest))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("EXTRACTED statement", result.stdout + result.stderr)
        self.assertFalse(self.output.exists())

    def test_v2_manifest_accepts_complete_literal_claims(self):
        source, source_root, manifest = self.source_backed()
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["version"] = 2
        payload["claims"][0]["artifactRef"] = "line:2"
        payload["claims"][0]["statement"] = "class Asset"
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        from render_native_diagram import _validate_source_manifest
        _, problems = _validate_source_manifest(manifest, source_root.resolve(), source,
                                               "mermaid", None)
        self.assertEqual(problems, [])

    def test_v2_manifest_inventories_local_plantuml_includes(self):
        from render_native_diagram import _validate_source_manifest
        source, source_root, manifest = self.source_backed()
        source = self.root / "view.puml"
        source.write_text("@startuml\n!include links.puml\nclass Asset\n@enduml\n", encoding="utf-8")
        (self.root / "links.puml").write_text("Asset --> Ledger\n", encoding="utf-8")
        payload = {"version": 2, "engine": "plantuml", "diagramType": "class",
                   "claims": [{"statement": "class Asset", "artifactRef": "line:3",
                               "artifactQuote": "class Asset", "provenance": "EXTRACTED",
                               "evidence": [{"path": "Asset.java", "line": 1,
                                             "quote": "class Asset"}]}]}
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        _, problems = _validate_source_manifest(manifest, source_root.resolve(), source,
                                               "plantuml", None)
        self.assertTrue(any("include:links.puml:line:1" in problem for problem in problems), problems)
        payload["claims"].append({"statement": "Asset links to Ledger",
                                  "artifactRef": "include:links.puml:line:1",
                                  "artifactQuote": "Asset --> Ledger", "provenance": "INFERRED",
                                  "evidence": [{"path": "Asset.java", "line": 1,
                                                "quote": "class Asset"}]})
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        _, problems = _validate_source_manifest(manifest, source_root.resolve(), source,
                                               "plantuml", None)
        self.assertEqual(problems, [])

    def test_plantuml_external_include_prevents_complete_claim_coverage(self):
        from render_native_diagram import _untracked_includes
        source = self.root / "view.puml"
        source.write_text("@startuml\n!include <C4/C4_Container>\nclass Asset\n@enduml\n",
                          encoding="utf-8")
        self.assertEqual(_untracked_includes(source), ["line:2"])

    def test_plantuml_block_include_inventories_only_selected_block(self):
        from render_native_diagram import _plantuml_refs
        source = self.root / "view.puml"
        source.write_text("@startuml\n!include blocks.puml!0\n@enduml\n", encoding="utf-8")
        (self.root / "blocks.puml").write_text(
            "@startuml\nclass Asset\n@enduml\n@startuml\nclass Unselected\n@enduml\n",
            encoding="utf-8")
        refs, untracked, included = _plantuml_refs(source)
        self.assertEqual(refs, {"include:blocks.puml:line:2": "class Asset"})
        self.assertEqual(untracked, [])
        self.assertEqual(included, [(self.root / "blocks.puml").resolve()])

    @unittest.skipUnless(shutil.which("plantuml"), "official PlantUML CLI is unavailable")
    def test_official_plantuml_selected_block_is_packaged(self):
        _, source_root, manifest = self.source_backed()
        source = self.root / "view.puml"
        source.write_text("@startuml\n!include blocks.puml!ASSET\n@enduml\n", encoding="utf-8")
        (self.root / "blocks.puml").write_text(
            "@startuml(id=ASSET)\nclass Asset\n@enduml\n"
            "@startuml(id=OTHER)\nclass Unselected\n@enduml\n", encoding="utf-8")
        manifest.write_text(json.dumps({"version": 2, "engine": "plantuml", "diagramType": "class",
                                        "claims": [{"statement": "class Asset",
                                                    "artifactRef": "include:blocks.puml:line:2",
                                                    "artifactQuote": "class Asset",
                                                    "provenance": "EXTRACTED",
                                                    "evidence": [{"path": "Asset.java", "line": 1,
                                                                  "quote": "class Asset"}]}]}), encoding="utf-8")
        result = self.render("plantuml", source, "--source-repo", str(source_root),
                             "--evidence", str(manifest))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["claimCoverage"], "complete")
        self.assertTrue((self.output / "blocks.puml").is_file())

    @unittest.skipUnless(shutil.which("plantuml"), "official PlantUML CLI is unavailable")
    def test_plantuml_includesub_is_packaged_and_claimed(self):
        _, source_root, manifest = self.source_backed()
        source = self.root / "view.puml"
        source.write_text("@startuml\n!includesub part.puml!BASIC\n@enduml\n", encoding="utf-8")
        (self.root / "part.puml").write_text(
            "@startuml\n!startsub BASIC\nclass Asset\n!endsub\n@enduml\n", encoding="utf-8")
        manifest.write_text(json.dumps({"version": 2, "engine": "plantuml", "diagramType": "class",
                                        "claims": [{"statement": "Asset view",
                                                    "artifactRef": "line:2",
                                                    "artifactQuote": "!includesub part.puml!BASIC",
                                                    "provenance": "INFERRED",
                                                    "evidence": [{"path": "Asset.java", "line": 1,
                                                                  "quote": "class Asset"}]}]}), encoding="utf-8")
        incomplete = self.render("plantuml", source, "--source-repo", str(source_root),
                                 "--evidence", str(manifest))
        self.assertNotEqual(incomplete.returncode, 0)
        self.assertIn("include:part.puml:line:3", incomplete.stdout + incomplete.stderr)
        manifest.write_text(json.dumps({"version": 2, "engine": "plantuml", "diagramType": "class",
                                        "claims": [{"statement": "class Asset",
                                                    "artifactRef": "include:part.puml:line:3",
                                                    "artifactQuote": "class Asset",
                                                    "provenance": "EXTRACTED",
                                                    "evidence": [{"path": "Asset.java", "line": 1,
                                                                  "quote": "class Asset"}]}]}), encoding="utf-8")
        result = self.render("plantuml", source, "--source-repo", str(source_root),
                             "--evidence", str(manifest))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["claimCoverage"], "complete")
        self.assertTrue((self.output / "part.puml").is_file())

    @unittest.skipUnless(shutil.which("plantuml"), "official PlantUML CLI is unavailable")
    def test_official_plantuml_local_include_is_packaged(self):
        _, source_root, manifest = self.source_backed()
        source = self.root / "view.puml"
        source.write_text("@startuml\n!include links.puml\nclass Asset\n@enduml\n", encoding="utf-8")
        (self.root / "links.puml").write_text("Asset --> Ledger\n", encoding="utf-8")
        manifest.write_text(json.dumps({"version": 2, "engine": "plantuml", "diagramType": "class",
                                        "claims": [
                                            {"statement": "class Asset", "artifactRef": "line:3",
                                             "artifactQuote": "class Asset", "provenance": "EXTRACTED",
                                             "evidence": [{"path": "Asset.java", "line": 1,
                                                           "quote": "class Asset"}]},
                                            {"statement": "Asset links to Ledger",
                                             "artifactRef": "include:links.puml:line:1",
                                             "artifactQuote": "Asset --> Ledger", "provenance": "INFERRED",
                                             "evidence": [{"path": "Asset.java", "line": 1,
                                                           "quote": "class Asset"}]}]}), encoding="utf-8")
        result = self.render("plantuml", source, "--source-repo", str(source_root),
                             "--evidence", str(manifest))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["claimCoverage"], "complete")
        self.assertTrue((self.output / "links.puml").is_file())

    @unittest.skipUnless(shutil.which("plantuml"), "official PlantUML CLI is unavailable")
    def test_official_plantuml_library_include_reports_partial_coverage(self):
        _, source_root, manifest = self.source_backed()
        source = self.root / "view.puml"
        source.write_text('@startuml\n!include <C4/C4_Container>\n'
                          'Container(asset, "Asset", "Java", "Stores data")\n@enduml\n',
                          encoding="utf-8")
        manifest.write_text(json.dumps({"version": 2, "engine": "plantuml", "diagramType": "c4-container",
                                        "claims": [{"statement": "Asset container", "artifactRef": "line:3",
                                                    "artifactQuote": "Container(asset", "provenance": "INFERRED",
                                                    "evidence": [{"path": "Asset.java", "line": 1,
                                                                  "quote": "class Asset"}]}]}), encoding="utf-8")
        result = self.render("plantuml", source, "--source-repo", str(source_root),
                             "--evidence", str(manifest))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["claimCoverage"], "partial")
        self.assertEqual(receipt["untrackedIncludes"], ["line:2"])

    def test_v2_manifest_covers_drawio_cells_and_archify_items(self):
        from render_native_diagram import _validate_source_manifest
        source, source_root, manifest = self.source_backed()
        source = self.root / "view.drawio"
        source.write_text('<mxfile><diagram><mxGraphModel><root>'
                          '<mxCell id="0"/><mxCell id="1" parent="0"/>'
                          '<mxCell id="a" value="Asset" vertex="1" parent="1"/>'
                          '<mxCell id="b" value="Ledger" vertex="1" parent="1"/>'
                          '<mxCell id="ab" edge="1" source="a" target="b" parent="1"/>'
                          '</root></mxGraphModel></diagram></mxfile>', encoding="utf-8")
        payload = {"version": 2, "engine": "drawio", "diagramType": "architecture",
                   "claims": [{"statement": "Asset", "artifactRef": "cell:a",
                               "artifactQuote": 'id="a"', "provenance": "INFERRED",
                               "evidence": [{"path": "Asset.java", "line": 1,
                                             "quote": "class Asset"}]}]}
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        _, problems = _validate_source_manifest(manifest, source_root.resolve(), source,
                                               "drawio", None)
        self.assertTrue(any("cell:b" in problem and "cell:ab" in problem
                            for problem in problems), problems)

        source = self.root / "view.archify.json"
        source.write_text(json.dumps({"diagram_type": "architecture",
                                      "components": [{"id": "asset", "label": "Asset"},
                                                     {"id": "ledger", "label": "Ledger"}],
                                      "boundaries": [],
                                      "connections": [{"from": "asset", "to": "ledger"}]}),
                          encoding="utf-8")
        payload["engine"] = "archify"
        payload["claims"][0]["artifactRef"] = "/components/0"
        payload["claims"][0]["artifactQuote"] = '"Asset"'
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        _, problems = _validate_source_manifest(manifest, source_root.resolve(), source,
                                               "archify", "architecture")
        self.assertTrue(any("/components/1" in problem and "/connections/0" in problem
                            for problem in problems), problems)

    def test_rejects_wrong_engine_or_provenance_in_evidence_manifest(self):
        for options, expected in (({"engine": "plantuml"}, "engine"),
                                  ({"provenance": "GUESSED"}, "provenance")):
            with self.subTest(options=options):
                source, source_root, manifest = self.source_backed(**options)
                result = self.render("mermaid", source, "--source-repo", str(source_root),
                                     "--evidence", str(manifest))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stdout + result.stderr)
                self.assertFalse(self.output.exists())

    def test_rejects_source_evidence_outside_repository(self):
        source, source_root, manifest = self.source_backed(path="../outside.java")
        (self.root / "outside.java").write_text("class Asset {}\n", encoding="utf-8")
        result = self.render("mermaid", source, "--source-repo", str(source_root),
                             "--evidence", str(manifest))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("outside source root", result.stdout + result.stderr)
        self.assertFalse(self.output.exists())

    def test_rejects_archify_manifest_type_mismatch_before_writing(self):
        source, source_root, manifest = self.source_backed(engine="archify", diagram_type="sequence",
                                                           artifact_quote='"diagram_type": "workflow"')
        source = self.root / "workflow.json"
        source.write_text('{"diagram_type": "workflow", "schema_version": 1}', encoding="utf-8")
        result = self.render("archify", source, "--source-repo", str(source_root),
                             "--evidence", str(manifest))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("diagramType must be workflow", result.stdout + result.stderr)
        self.assertFalse(self.output.exists())

    @unittest.skipUnless(os.environ.get("MERMAID_OFFICIAL_CLI") or shutil.which("mmdc"),
                         "official Mermaid CLI unavailable")
    def test_source_backed_native_diagram_checks_claim_anchors_and_exports(self):
        source, source_root, manifest = self.source_backed()
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["version"] = 2
        payload["claims"][0]["artifactRef"] = "line:2"
        payload["claims"][0]["statement"] = "class Asset"
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        executable = os.environ.get("MERMAID_OFFICIAL_CLI") or shutil.which("mmdc")
        result = self.render("mermaid", source, "--source-repo", str(source_root),
                             "--evidence", str(manifest), "--engine-cli", executable,
                             "--export", "png")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["sourceEvidence"], "anchors_validated")
        self.assertEqual(receipt["claimCoverage"], "complete")
        self.assertEqual(receipt["claimSemantics"], "not_proven")
        self.assertEqual(receipt["claimCount"], 1)
        self.assertEqual(receipt["declaredDiagramType"], "class")
        self.assertIn(str((self.output / "diagram.evidence.json").resolve()), receipt["artifacts"])
        self.assertTrue((self.output / "diagram.mermaid.png").is_file())

    @unittest.skipUnless(os.environ.get("MERMAID_OFFICIAL_CLI") or shutil.which("mmdc"),
                         "official Mermaid CLI unavailable")
    def test_run_without_manifest_removes_stale_evidence_copy(self):
        source, source_root, manifest = self.source_backed()
        executable = os.environ.get("MERMAID_OFFICIAL_CLI") or shutil.which("mmdc")
        first = self.render("mermaid", source, "--source-repo", str(source_root),
                            "--evidence", str(manifest), "--engine-cli", executable)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertTrue((self.output / "diagram.evidence.json").is_file())
        second = self.render("mermaid", source, "--engine-cli", executable)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertFalse((self.output / "diagram.evidence.json").exists())

    def test_rejects_wrong_native_extension_before_writing(self):
        source = self.root / "diagram.txt"
        source.write_text("classDiagram\nA <|-- B\n", encoding="utf-8")
        result = self.render("mermaid", source)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(".mmd", result.stdout + result.stderr)
        self.assertFalse(self.output.exists())

    def test_rejects_unknown_archify_type_before_writing(self):
        source = self.root / "unknown.json"
        source.write_text('{"diagram_type":"unknown","schema_version":1}', encoding="utf-8")
        result = self.render("archify", source, "--engine-cli", str(self.root / "missing-archify"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported Archify diagram_type", result.stdout + result.stderr)
        self.assertFalse(self.output.exists())

    def test_rejects_archify_quality_flag_for_other_engines(self):
        source = self.root / "diagram.mmd"
        source.write_text("flowchart LR\nA-->B\n", encoding="utf-8")
        result = self.render("mermaid", source, "--quality", "showcase")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Archify", result.stdout + result.stderr)
        self.assertFalse(self.output.exists())

    @unittest.skipUnless(os.environ.get("MERMAID_OFFICIAL_CLI") or shutil.which("mmdc"),
                         "official Mermaid CLI unavailable")
    def test_official_mermaid_class_diagram_native_export(self):
        source = self.root / "classes.mmd"
        source.write_text("classDiagram\n  class Asset\n  class Event\n  Asset --> Event : creates\n",
                          encoding="utf-8")
        executable = os.environ.get("MERMAID_OFFICIAL_CLI") or shutil.which("mmdc")
        result = self.render("mermaid", source, "--engine-cli", executable, "--export", "png")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["officialCheck"], "pass")
        self.assertEqual(receipt["sourceEvidence"], "not_checked")
        self.assertIn(str((self.output / "diagram.mermaid.png").resolve()), receipt["artifacts"])
        self.assertTrue((self.output / "diagram.mmd").read_text().startswith("classDiagram"))

    @unittest.skipUnless(os.environ.get("PLANTUML_OFFICIAL_CLI") or shutil.which("plantuml"),
                         "official PlantUML CLI unavailable")
    def test_official_plantuml_activity_diagram_native_validation(self):
        source = self.root / "activity.puml"
        source.write_text("@startuml\nstart\n:Receive request;\nstop\n@enduml\n", encoding="utf-8")
        executable = os.environ.get("PLANTUML_OFFICIAL_CLI") or shutil.which("plantuml")
        result = self.render("plantuml", source, "--engine-cli", executable)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["officialCheck"], "pass")
        self.assertTrue((self.output / "diagram.puml").is_file())

    @unittest.skipUnless(os.environ.get("DRAWIO_OFFICIAL_CLI") or shutil.which("drawio"),
                         "official draw.io CLI unavailable")
    def test_official_drawio_freeform_diagram_native_export(self):
        source = self.root / "freeform.drawio"
        source.write_text('<mxfile><diagram id="one" name="One"><mxGraphModel><root>'
                          '<mxCell id="0"/><mxCell id="1" parent="0"/>'
                          '<mxCell id="n" value="Node" vertex="1" parent="1">'
                          '<mxGeometry x="40" y="40" width="140" height="60" as="geometry"/>'
                          '</mxCell></root></mxGraphModel></diagram></mxfile>', encoding="utf-8")
        executable = os.environ.get("DRAWIO_OFFICIAL_CLI") or shutil.which("drawio")
        result = self.render("drawio", source, "--engine-cli", executable, "--export", "png")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.output / "diagram.drawio.png").is_file())

    @unittest.skipUnless(ARCHIFY_EXAMPLES and ARCHIFY_EXAMPLES.is_dir(),
                         "official Archify CLI/examples unavailable")
    def test_official_archify_accepts_all_five_native_modes(self):
        examples = {"architecture": "web-app.architecture.json",
                    "workflow": "incident-response.workflow.json",
                    "sequence": "cache-miss-request.sequence.json",
                    "dataflow": "event-stream.dataflow.json",
                    "lifecycle": "agent-run.lifecycle.json"}
        executable = ARCHIFY_CLI
        for kind, filename in examples.items():
            with self.subTest(kind=kind):
                self.output = self.root / kind
                result = self.render("archify", ARCHIFY_EXAMPLES / filename,
                                     "--engine-cli", executable,
                                     *(["--export", "png"] if kind == "architecture" else []))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                receipt = json.loads(result.stdout)
                self.assertEqual(receipt["diagramType"], kind)
                self.assertEqual(receipt["officialCheck"], "pass")
                self.assertTrue((self.output / "diagram.archify.html").is_file())
                if kind == "architecture":
                    self.assertTrue((self.output / "diagram.archify.png").is_file())

    @unittest.skipUnless(os.environ.get("MERMAID_OFFICIAL_CLI") or shutil.which("mmdc"),
                         "official Mermaid CLI unavailable")
    def test_invalid_native_source_fails_without_stale_export(self):
        source = self.root / "broken.mmd"
        source.write_text("this is not Mermaid syntax\n", encoding="utf-8")
        self.output.mkdir()
        stale = self.output / "diagram.mermaid.png"
        stale.write_bytes(b"old")
        executable = os.environ.get("MERMAID_OFFICIAL_CLI") or shutil.which("mmdc")
        result = self.render("mermaid", source, "--engine-cli", executable, "--export", "png")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(stale.exists())


if __name__ == "__main__":
    unittest.main()
