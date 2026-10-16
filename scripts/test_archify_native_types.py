"""Archify 3.1 native types: dispatch, source coverage and official delivery."""

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from engine_paths import find_engine
from render_native_diagram import _material_refs, _validate_source_manifest


SCRIPT = Path(__file__).with_name("render_native_diagram.py")
ARCHIFY = find_engine("archify")
EXAMPLES = Path(ARCHIFY).resolve().parent.parent / "examples" if ARCHIFY else None
OFFICIAL_REQUESTED = bool(os.environ.get("ARCHIFY_OFFICIAL_CLI"))
OFFICIAL_EXAMPLES = {"erd": "orders.erd.json", "tree": "payment-platform.tree.json", "class": "payments.class.json",
                     "timeline": "payment-incident.timeline.json", "waterfall": "checkout-request.waterfall.json"}
NEW_TYPES = {
    "erd": {"entities": [{"id": "asset", "label": "Asset", "attributes": [{"name": "id", "type": "bigint", "key": "pk"}]},
                         {"id": "ledger", "label": "Ledger"}],
            "relationships": [{"from": "asset", "to": "ledger", "fromCardinality": "many", "toCardinality": "one"}]},
    "tree": {"nodes": [{"id": "asset", "label": "Asset"}, {"id": "ledger", "label": "Ledger", "parent": "asset"}]},
    "class": {"types": [{"id": "asset", "label": "Asset", "kind": "class", "methods": [{"name": "save"}]},
                         {"id": "ledger", "label": "Ledger", "kind": "interface"}],
              "relationships": [{"from": "asset", "to": "ledger", "kind": "realization"}]},
    "timeline": {"lanes": [{"id": "release", "label": "Release"}],
                 "events": [{"id": "asset", "title": "Asset", "at": "2026-10-16T10:00:00+08:00", "lane": "release"},
                            {"id": "ledger", "title": "Ledger", "at": "2026-10-16T02:01:00Z", "lane": "release"}]},
    "waterfall": {"spans": [{"id": "asset", "name": "Asset", "start": 0, "duration": 10},
                            {"id": "ledger", "name": "Ledger", "start": 2, "end": 8, "parent": "asset"}]},
}


class ArchifyNativeTypesTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="archify native types ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        (self.repo / "Asset.java").write_text("class Asset {}\n", encoding="utf-8")
        self.output = self.root / "output"
        self.manifest = self.root / "evidence.json"

    def fixture(self, kind):
        payload = {"schema_version": 1, "diagram_type": kind,
                   "meta": {"title": "Asset view", "output": "asset.html"}, **copy.deepcopy(NEW_TYPES[kind])}
        if kind in {"timeline", "waterfall"}:
            payload["meta"]["evidence"] = "illustrative"
        source = self.root / f"{kind}.json"
        source.write_text(json.dumps(payload), encoding="utf-8")
        claims = [{"statement": "Asset view inferred from its declaration", "artifactRef": f"/{key}/{index}",
                   "artifactQuote": json.dumps(item), "provenance": "INFERRED",
                   "evidence": [{"path": "Asset.java", "line": 1, "quote": "class Asset"}]}
                  for key, items in NEW_TYPES[kind].items() for index, item in enumerate(items)]
        manifest = {"version": 2, "engine": "archify", "diagramType": kind, "claims": claims}
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")
        return source, manifest

    def render(self, kind, source, cli, *extra):
        return subprocess.run([sys.executable, str(SCRIPT), "--engine", "archify", "--input", str(source),
                               "--output", str(self.output / kind), "--engine-cli", str(cli), *extra],
                              capture_output=True, text=True, timeout=180)

    def test_new_types_dispatch_and_preserve_source_backed_receipts(self):
        cli = self.root / "archify"
        cli.write_text(f"#!{sys.executable}\nimport json,sys\nfrom pathlib import Path\n"
                       "assert sys.argv[1] == 'deliver'\n"
                       "assert json.loads(Path(sys.argv[3]).read_text())['diagram_type'] == sys.argv[2]\n"
                       "Path(sys.argv[4]).write_text('<html>validated by fixture</html>')\n"
                       "print(json.dumps({'ok': True, 'command': 'deliver'}))\n")
        cli.chmod(0o755)
        for kind in NEW_TYPES:
            with self.subTest(kind=kind):
                source, manifest = self.fixture(kind)
                result = self.render(kind, source, cli, "--source-repo", str(self.repo), "--evidence", str(self.manifest))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                receipt = json.loads(result.stdout)
                self.assertEqual(receipt["diagramType"], kind)
                self.assertEqual(receipt["sourceEvidence"], "anchors_validated")
                self.assertEqual(receipt["claimCoverage"], "complete")
                self.assertEqual(receipt["claimSemantics"], "not_proven")
                self.assertEqual(receipt["claimCount"], len(manifest["claims"]))
                self.assertEqual((self.output / kind / "diagram.archify.json").read_bytes(), source.read_bytes())
                self.assertEqual(len(receipt["artifacts"]), 3)

    def test_inventory_includes_all_entities_relationships_nodes_types_lanes_events_and_spans(self):
        for kind in NEW_TYPES:
            with self.subTest(kind=kind):
                source, manifest = self.fixture(kind)
                refs = _material_refs(source, "archify", kind)
                self.assertEqual(set(refs), {claim["artifactRef"] for claim in manifest["claims"]})
                _, problems = _validate_source_manifest(self.manifest, self.repo, source, "archify", kind)
                self.assertEqual(problems, [])

    def test_every_omitted_material_item_is_rejected(self):
        for kind in NEW_TYPES:
            source, manifest = self.fixture(kind)
            for omitted in manifest["claims"]:
                with self.subTest(kind=kind, omitted=omitted["artifactRef"]):
                    partial = dict(manifest, claims=[claim for claim in manifest["claims"] if claim != omitted])
                    self.manifest.write_text(json.dumps(partial))
                    _, problems = _validate_source_manifest(self.manifest, self.repo, source, "archify", kind)
                    self.assertTrue(any("lacks claims for" in error and omitted["artifactRef"] in error
                                        for error in problems), problems)

    def test_quote_must_belong_to_the_referenced_item(self):
        for kind in NEW_TYPES:
            with self.subTest(kind=kind):
                source, manifest = self.fixture(kind)
                manifest["claims"][0]["artifactQuote"] = "Ledger"
                self.manifest.write_text(json.dumps(manifest))
                _, problems = _validate_source_manifest(self.manifest, self.repo, source, "archify", kind)
                self.assertTrue(any("artifactQuote must occur in" in error for error in problems), problems)

    def test_optional_collections_can_be_absent_or_empty(self):
        optional = [("erd", "relationships"), ("class", "relationships"), ("timeline", "lanes")]
        for kind, field in [*optional, *((kind, "cards") for kind in NEW_TYPES)]:
            for present in (False, True):
                with self.subTest(kind=kind, field=field, present=present):
                    source, manifest = self.fixture(kind)
                    payload = json.loads(source.read_text())
                    payload.pop(field, None)
                    if present:
                        payload[field] = []
                    source.write_text(json.dumps(payload))
                    manifest["claims"] = [claim for claim in manifest["claims"] if not claim["artifactRef"].startswith(f"/{field}/")]
                    self.manifest.write_text(json.dumps(manifest))
                    _, problems = _validate_source_manifest(self.manifest, self.repo, source, "archify", kind)
                    self.assertEqual(problems, [])

    def test_factual_cards_require_claims_and_can_be_fully_covered(self):
        for kind in NEW_TYPES:
            with self.subTest(kind=kind):
                source, manifest = self.fixture(kind)
                payload = json.loads(source.read_text())
                card = {"title": "Asset rules", "items": ["Asset owns a ledger", "Ledger entries are retained"]}
                payload["cards"] = [card]
                source.write_text(json.dumps(payload))
                _, problems = _validate_source_manifest(self.manifest, self.repo, source, "archify", kind)
                self.assertTrue(any("lacks claims for: /cards/0" in error for error in problems), problems)
                manifest["claims"].append(dict(manifest["claims"][0], artifactRef="/cards/0", artifactQuote="Ledger entries are retained"))
                self.manifest.write_text(json.dumps(manifest))
                _, problems = _validate_source_manifest(self.manifest, self.repo, source, "archify", kind)
                self.assertEqual(problems, [])

    def test_malformed_cards_are_rejected_during_inventory(self):
        for kind in NEW_TYPES:
            for cards in (None, "rules", {"title": "Asset rules"}):
                with self.subTest(kind=kind, cards=cards):
                    source, _ = self.fixture(kind)
                    payload = json.loads(source.read_text())
                    payload["cards"] = cards
                    source.write_text(json.dumps(payload))
                    _, problems = _validate_source_manifest(self.manifest, self.repo, source, "archify", kind)
                    self.assertTrue(any("cannot be inventoried" in error and "cards" in error for error in problems), problems)

    def test_invalid_material_collection_reports_error_instead_of_complete_coverage(self):
        for kind, arrays in NEW_TYPES.items():
            for field in arrays:
                for invalid in (None, "items", {"id": "asset"}):
                    with self.subTest(kind=kind, field=field, invalid=invalid):
                        source, _ = self.fixture(kind)
                        payload = json.loads(source.read_text())
                        payload[field] = invalid
                        source.write_text(json.dumps(payload))
                        _, problems = _validate_source_manifest(self.manifest, self.repo, source, "archify", kind)
                        self.assertTrue(any("cannot be inventoried" in error and field in error for error in problems), problems)

    def test_missing_or_empty_required_material_collection_is_rejected_before_engine_lookup(self):
        for kind, required in (("erd", "entities"), ("tree", "nodes"), ("class", "types"),
                               ("timeline", "events"), ("waterfall", "spans")):
            for empty in (False, True):
                with self.subTest(kind=kind, empty=empty):
                    source, manifest = self.fixture(kind)
                    payload = json.loads(source.read_text())
                    payload.pop(required)
                    if empty:
                        payload[required] = []
                    source.write_text(json.dumps(payload))
                    manifest["claims"] = [claim for claim in manifest["claims"]
                                          if not claim["artifactRef"].startswith(f"/{required}/")]
                    self.manifest.write_text(json.dumps(manifest))
                    _, problems = _validate_source_manifest(self.manifest, self.repo, source, "archify", kind)
                    self.assertTrue(any("cannot be inventoried" in error and required in error for error in problems), problems)
                    result = self.render(kind, source, self.root / "absent-cli", "--source-repo", str(self.repo),
                                         "--evidence", str(self.manifest))
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("cannot be inventoried", result.stderr)
                    self.assertFalse(self.output.exists())

    def test_type_mismatch_and_bad_source_anchor_fail_before_writing(self):
        for kind in NEW_TYPES:
            for bad_type in (False, True):
                with self.subTest(kind=kind, bad_type=bad_type):
                    source, manifest = self.fixture(kind)
                    if bad_type:
                        manifest["diagramType"] = "architecture"
                    else:
                        manifest["claims"][0]["evidence"][0]["quote"] = "class Missing"
                    self.manifest.write_text(json.dumps(manifest))
                    result = self.render(kind, source, self.root / "absent-cli", "--source-repo", str(self.repo),
                                         "--evidence", str(self.manifest))
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(f"diagramType must be {kind}" if bad_type else "quote does not occur", result.stderr)
                    self.assertFalse(self.output.exists())

    def test_invalid_diagram_type_values_return_validation_errors_without_tracebacks(self):
        for invalid in ([], {}, ["erd"], 1, None):
            with self.subTest(invalid=invalid):
                source = self.root / "invalid.json"
                source.write_text(json.dumps({"diagram_type": invalid}))
                result = self.render("invalid", source, self.root / "absent-cli")
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("Traceback", result.stderr)
                self.assertIn("unsupported Archify diagram_type", result.stderr)
                self.assertFalse(self.output.exists())

    def test_invalid_manifest_scalar_types_return_validation_errors_before_writing(self):
        cases = [("version", value) for value in ([], {}, True, 2.0)]
        cases += [("artifactRef", value) for value in ([], {}, 0)]
        cases += [("provenance", value) for value in ([], {})]
        for kind in NEW_TYPES:
            for field, invalid in cases:
                with self.subTest(kind=kind, field=field, invalid=invalid):
                    source, manifest = self.fixture(kind)
                    container = manifest if field == "version" else manifest["claims"][0]
                    container[field] = invalid
                    self.manifest.write_text(json.dumps(manifest))
                    result = self.render(kind, source, self.root / "absent-cli", "--source-repo", str(self.repo),
                                         "--evidence", str(self.manifest))
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertIn(field, result.stderr)
                    self.assertFalse(self.output.exists())

    def test_failed_official_delivery_removes_partial_html(self):
        cli = self.root / "failing-archify"
        for mode in ("exit", "invalid-json", "rejected", "wrong-command"):
            stdout = "not JSON" if mode == "invalid-json" else json.dumps(
                {"ok": mode != "rejected", "command": "render" if mode == "wrong-command" else "deliver"})
            cli.write_text(f"#!{sys.executable}\nimport sys\nfrom pathlib import Path\n"
                           "Path(sys.argv[4]).write_text('<html>partial unvalidated artifact</html>')\n"
                           f"print({stdout!r})\nsys.exit({1 if mode == 'exit' else 0})\n")
            cli.chmod(0o755)
            for kind in NEW_TYPES:
                with self.subTest(mode=mode, kind=kind):
                    source, _ = self.fixture(kind)
                    result = self.render(kind, source, cli)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(json.loads(result.stdout)["officialCheck"], "fail")
                    self.assertNotEqual(json.loads(result.stdout)["problems"], ["None"])
                    self.assertFalse((self.output / kind / "diagram.archify.html").exists())

    def test_workflow_and_lifecycle_paths_and_semantic_checks_require_evidence(self):
        for kind, node_key, edge_key in (("workflow", "nodes", "edges"), ("lifecycle", "states", "transitions")):
            source, _ = self.fixture("tree")
            payload = {"diagram_type": kind, node_key: [{"id": "asset"}, {"id": "ledger"}],
                       edge_key: [{"from": "asset", "to": "ledger"}], "mainPath": ["asset", "ledger"]}
            records = [(f"/{key}/{i}", item) for key, items in payload.items()
                       if isinstance(items, list) for i, item in enumerate(items)]
            if kind == "workflow":
                payload["semanticChecks"] = {"allowedRoots": ["asset"], "allowedTerminals": ["ledger"],
                                             "requiredEdges": [{"from": "asset", "to": "ledger"}],
                                             "requiredPaths": [{"from": "asset", "to": "ledger"}]}
                records.extend((f"/semanticChecks/{key}/{i}", item) for key, items in payload["semanticChecks"].items()
                               for i, item in enumerate(items))
            source.write_text(json.dumps(payload))
            claims = [{"artifactRef": ref, "artifactQuote": json.dumps(item), "statement": "Asset linkage",
                       "provenance": "INFERRED", "evidence": [{"path": "Asset.java", "line": 1, "quote": "class Asset"}]}
                      for ref, item in records]
            manifest = {"version": 2, "engine": "archify", "diagramType": kind, "claims": claims}
            for claim in claims:
                if not claim["artifactRef"].startswith(("/mainPath/", "/semanticChecks/")):
                    continue
                with self.subTest(kind=kind, omitted=claim["artifactRef"]):
                    self.manifest.write_text(json.dumps(dict(manifest, claims=[entry for entry in claims if entry != claim])))
                    _, problems = _validate_source_manifest(self.manifest, self.repo, source, "archify", kind)
                    self.assertTrue(any("lacks claims for" in error and claim["artifactRef"] in error for error in problems), problems)
            self.manifest.write_text(json.dumps(manifest))
            _, problems = _validate_source_manifest(self.manifest, self.repo, source, "archify", kind)
            self.assertEqual(problems, [])

    def test_malformed_workflow_semantic_checks_fail_inventory(self):
        for invalid in (None, [], "checks", {"requiredPaths": None}, {"allowedRoots": "asset"}):
            with self.subTest(invalid=invalid):
                source, _ = self.fixture("tree")
                source.write_text(json.dumps({"diagram_type": "workflow", "semanticChecks": invalid}))
                with self.assertRaisesRegex(ValueError, "semanticChecks"):
                    _material_refs(source, "archify", "workflow")

    def test_explicit_archify_acceptance_fails_when_official_examples_are_missing(self):
        cli = self.root / "empty-package/bin/archify"
        cli.parent.mkdir(parents=True)
        cli.write_text("#!/bin/sh\nexit 0\n")
        cli.chmod(0o755)
        test = "test_archify_native_types.ArchifyNativeTypesTest.test_official_new_types_deliver_and_export_all_formats"
        result = subprocess.run([sys.executable, "-m", "unittest", test], cwd=SCRIPT.parent,
                                env=dict(os.environ, ARCHIFY_OFFICIAL_CLI=str(cli)),
                                text=True, capture_output=True, timeout=30)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("official Archify examples", result.stderr)

    @unittest.skipUnless(OFFICIAL_REQUESTED or (EXAMPLES and EXAMPLES.is_dir()), "official Archify CLI/examples unavailable")
    def test_official_new_types_deliver_and_export_all_formats(self):
        self.assertTrue(EXAMPLES and EXAMPLES.is_dir(), "official Archify examples are required for explicit acceptance")
        signatures = {"png": b"\x89PNG\r\n\x1a\n", "jpg": b"\xff\xd8\xff", "webp": b"RIFF",
                      "pdf": b"%PDF-", "webm": b"\x1a\x45\xdf\xa3"}
        for kind, filename in OFFICIAL_EXAMPLES.items():
            with self.subTest(kind=kind):
                payload = json.loads((EXAMPLES / filename).read_text())
                payload["meta"]["animation"] = "trace"
                source = self.root / filename
                source.write_text(json.dumps(payload))
                result = self.render(kind, source, ARCHIFY, *[arg for fmt in ("svg", *signatures) for arg in ("--export", fmt)])
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                receipt = json.loads(result.stdout)
                self.assertEqual(receipt["diagramType"], kind)
                self.assertEqual(receipt["officialCheck"], "pass")
                self.assertEqual(receipt["exportCheck"], "pass")
                self.assertEqual(receipt["sourceEvidence"], "not_checked")
                self.assertTrue((self.output / kind / "diagram.archify.html").is_file())
                svg = (self.output / kind / "diagram.archify.svg").read_text()
                self.assertIn("<svg", svg)
                for fmt, signature in signatures.items():
                    artifact = self.output / kind / f"diagram.archify.{fmt}"
                    self.assertTrue(artifact.read_bytes().startswith(signature), artifact)
                    self.assertGreater(artifact.stat().st_size, 100)
                    self.assertIn(str(artifact), receipt["artifacts"])

    @unittest.skipUnless(OFFICIAL_REQUESTED or (EXAMPLES and EXAMPLES.is_dir()), "official Archify CLI/examples unavailable")
    def test_official_new_types_reject_invalid_semantics_and_remove_stale_exports(self):
        self.assertTrue(EXAMPLES and EXAMPLES.is_dir(), "official Archify examples are required for explicit acceptance")
        for kind, filename in OFFICIAL_EXAMPLES.items():
            with self.subTest(kind=kind):
                payload = json.loads((EXAMPLES / filename).read_text())
                if kind == "erd":
                    payload["relationships"][0]["fromCardinality"] = "few"
                elif kind == "tree":
                    payload["nodes"][0]["parent"] = payload["nodes"][1]["id"]
                elif kind == "class":
                    payload["relationships"][0]["to"] = "missing_type"
                elif kind == "timeline":
                    payload["events"][0]["at"] = "2026-10-16T10:00:00"
                else:
                    payload["spans"][1]["duration"] = -1
                source = self.root / filename
                source.write_text(json.dumps(payload))
                output = self.output / kind
                output.mkdir(parents=True)
                for suffix in ("html", "png"):
                    (output / f"diagram.archify.{suffix}").write_text("stale")
                result = self.render(kind, source, ARCHIFY)
                self.assertNotEqual(result.returncode, 0)
                receipt = json.loads(result.stdout)
                self.assertFalse(receipt["valid"])
                self.assertEqual(receipt["officialCheck"], "fail")
                self.assertTrue(receipt["problems"])
                self.assertFalse((output / "diagram.archify.html").exists())
                self.assertFalse((output / "diagram.archify.png").exists())


if __name__ == "__main__":
    unittest.main()
