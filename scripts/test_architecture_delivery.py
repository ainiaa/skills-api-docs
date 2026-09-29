"""Regression tests for strict architecture inventory and bundle delivery."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from architecture_candidates import discover_candidates
from architecture_landscape import check_landscape_geometry, render_landscape


CLI = Path(__file__).with_name("generate_architecture.py")


class ArchitectureDeliveryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        src = self.root / "src"
        src.mkdir()
        (src / "service").mkdir()
        (src / "PaymentController.java").write_text(
            '@RestController\nclass PaymentController {\n  @PostMapping("/payments")\n  void pay() {}\n}\n',
            encoding="utf-8")
        (src / "LedgerClient.java").write_text(
            '@FeignClient(name = "ledger")\ninterface LedgerClient {}\n', encoding="utf-8")
        (src / "service" / "PaymentService.java").write_text(
            'class PaymentService {\n  RedisTemplate redisTemplate;\n}\n', encoding="utf-8")
        (src / "PaymentMapper.java").write_text(
            '@Mapper\ninterface PaymentMapper {}\n', encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def _run(self, *args):
        return subprocess.run([sys.executable, str(CLI), *map(str, args)],
                              capture_output=True, text=True)

    def _fixture(self):
        inventory = discover_candidates(self.root)
        (self.root / "candidates.json").write_text(json.dumps(inventory), encoding="utf-8")
        kinds = {candidate["kind"]: candidate for candidate in inventory["candidates"]}
        self.assertEqual(set(kinds), {"entrypoint", "external_client", "cache_usage", "database"})

        def element(ident, kind, name, candidate):
            return {"id": ident, "type": kind, "name": name, "description": name,
                    "provenance": "INFERRED", "evidence": [candidate["evidence"]]}

        overview = {"version": 2, "profile": "architecture-landscape", "title": "Payments",
                    "scope": {"system": "Payments", "container": "Payment service"},
                    "elements": [element("api", "entrypoint", "API", kinds["entrypoint"]),
                                 element("ledger", "external_system", "Ledger", kinds["external_client"]),
                                 element("db", "database", "Database", kinds["database"])],
                    "relations": [],
                    "coverage": {"inventoryFile": "candidates.json", "decisions": [
                        {"candidateId": kinds["entrypoint"]["id"], "status": "overview", "element": "api"},
                        {"candidateId": kinds["external_client"]["id"], "status": "overview", "element": "ledger"},
                        {"candidateId": kinds["database"]["id"], "status": "overview", "element": "db"},
                        {"candidateId": kinds["cache_usage"]["id"], "status": "detail",
                         "relation": {"from": "pay", "to": "redis", "label": "Uses Redis"},
                         "detailView": "cache-detail.json", "reason": "Runtime detail"}]}}
        detail = {"version": 2, "profile": "architecture-landscape", "title": "Payment cache",
                  "scope": {"system": "Payments", "container": "Payment service"},
                  "elements": [element("pay", "service", "Payment", kinds["cache_usage"]),
                               element("redis", "cache", "Redis", kinds["cache_usage"])],
                  "relations": [{"from": "pay", "to": "redis", "label": "Uses Redis",
                                 "kind": "dependency", "provenance": "INFERRED",
                                 "evidence": [kinds["cache_usage"]["evidence"]]}],
                  "coverage": {"omitted": []}}
        overview_path = self.root / "overview.json"
        overview_path.write_text(json.dumps(overview), encoding="utf-8")
        (self.root / "cache-detail.json").write_text(json.dumps(detail), encoding="utf-8")
        return inventory, overview, overview_path

    def test_generated_inventory_requires_every_candidate_to_have_a_decision(self):
        inventory, overview, path = self._fixture()
        valid = self._run("validate", "--source", self.root, "--ir", path, "--strict-coverage")
        self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
        self.assertEqual(json.loads(valid.stdout)["coverageCheck"], "pass")
        overview["coverage"]["decisions"].pop()
        path.write_text(json.dumps(overview), encoding="utf-8")
        missing = self._run("validate", "--source", self.root, "--ir", path, "--strict-coverage")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("unclassified candidate", missing.stdout + missing.stderr)
        overview["coverage"]["decisions"] = []
        path.write_text(json.dumps(overview), encoding="utf-8")
        empty = self._run("validate", "--source", self.root, "--ir", path, "--strict-coverage")
        self.assertNotEqual(empty.returncode, 0)

    def test_inventory_detects_changed_source_and_invalid_detail_mapping(self):
        _, overview, path = self._fixture()
        (self.root / "src" / "service" / "PaymentService.java").write_text(
            'class PaymentService {\n  RedisTemplate cache;\n}\n', encoding="utf-8")
        stale = self._run("validate", "--source", self.root, "--ir", path, "--strict-coverage")
        self.assertNotEqual(stale.returncode, 0)
        self.assertIn("inventory is stale", stale.stdout + stale.stderr)
        (self.root / "src" / "service" / "PaymentService.java").write_text(
            'class PaymentService {\n  RedisTemplate redisTemplate;\n}\n', encoding="utf-8")
        overview["coverage"]["decisions"][-1]["relation"]["label"] = "Missing"
        path.write_text(json.dumps(overview), encoding="utf-8")
        bad = self._run("validate", "--source", self.root, "--ir", path, "--strict-coverage")
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("missing relation", bad.stdout + bad.stderr)

    def test_manual_codegraph_candidate_is_also_accounted_for(self):
        _, overview, path = self._fixture()
        overview["coverage"]["manualCandidates"] = [{
            "id": "manual_payment_flow", "kind": "relationship",
            "evidence": {"path": "src/service/PaymentService.java", "line": 2,
                         "quote": "RedisTemplate redisTemplate"}}]
        path.write_text(json.dumps(overview), encoding="utf-8")
        missing = self._run("validate", "--source", self.root, "--ir", path, "--strict-coverage")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("manual_payment_flow", missing.stdout + missing.stderr)
        overview["coverage"]["decisions"].append({
            "candidateId": "manual_payment_flow", "status": "excluded",
            "reason": "The aggregate cache dependency is already represented by the detail view"})
        path.write_text(json.dumps(overview), encoding="utf-8")
        good = self._run("validate", "--source", self.root, "--ir", path, "--strict-coverage")
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)

    def test_inventory_preserves_distinct_controller_entry_groups(self):
        for group in ("admin", "manage"):
            directory = self.root / "src" / "controller" / group
            directory.mkdir(parents=True)
            (directory / "Api.java").write_text(
                f'@RestController\nclass Api {{\n  @GetMapping("/{group}")\n  void get() {{}}\n}}\n',
                encoding="utf-8")
        inventory = discover_candidates(self.root)
        entrypoints = [item for item in inventory["candidates"] if item["kind"] == "entrypoint"]
        self.assertEqual(len(entrypoints), 3)

    def test_inventory_detects_custom_http_mapping_with_multiline_arguments(self):
        directory = self.root / "src" / "controller" / "admin"
        directory.mkdir(parents=True)
        (directory / "AdminApi.java").write_text(
            '@RestController\nclass AdminApi {\n  @HttpApiPostMapping(\n'
            '      name = "Sync",\n      value = "/admin/sync"\n  )\n'
            '  void sync() {}\n}\n', encoding="utf-8")
        inventory = discover_candidates(self.root)
        paths = [item["evidence"]["path"] for item in inventory["candidates"]
                 if item["kind"] == "entrypoint"]
        self.assertIn("src/controller/admin/AdminApi.java", paths)

    def test_inventory_detects_multiline_standard_mapping(self):
        (self.root / "src" / "PaymentController.java").write_text(
            '@RestController\nclass PaymentController {\n  @GetMapping(\n'
            '    value = "/payments"\n  )\n  void list() {}\n}\n', encoding="utf-8")
        inventory = discover_candidates(self.root)
        self.assertTrue(any(item["kind"] == "entrypoint" and
                            item["evidence"]["path"] == "src/PaymentController.java"
                            for item in inventory["candidates"]))

    def test_jobs_in_separate_files_need_separate_decisions(self):
        for name in ("First", "Second"):
            (self.root / "src" / f"{name}Job.java").write_text(
                f'class {name}Job {{\n  @XxlJob("{name.lower()}")\n}}\n', encoding="utf-8")
        inventory = discover_candidates(self.root)
        jobs = [item for item in inventory["candidates"] if item["kind"] == "scheduler"]
        self.assertEqual(len(jobs), 2)
        (self.root / "candidates.json").write_text(json.dumps(inventory), encoding="utf-8")
        first = jobs[0]
        overview = {"version": 2, "profile": "architecture-landscape", "title": "Jobs",
                    "scope": {"system": "Payments", "container": "Payment service"},
                    "elements": [{"id": "job", "type": "entrypoint", "name": "First job",
                                  "description": "First job only", "provenance": "INFERRED",
                                  "evidence": [first["evidence"]]}], "relations": [],
                    "coverage": {"inventoryFile": "candidates.json", "decisions": [
                        {"candidateId": item["id"], "status": "excluded", "reason": "Outside job view"}
                        for item in inventory["candidates"] if item["kind"] != "scheduler"] + [
                        {"candidateId": first["id"], "status": "overview", "element": "job"}]}}
        path = self.root / "overview.json"
        path.write_text(json.dumps(overview), encoding="utf-8")
        result = self._run("validate", "--source", self.root, "--ir", path, "--strict-coverage")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unclassified candidate", result.stdout + result.stderr)

    def test_mapping_requires_the_candidate_anchor_not_just_the_file(self):
        inventory, overview, path = self._fixture()
        entry = next(item for item in inventory["candidates"] if item["kind"] == "entrypoint")
        overview["elements"][0]["evidence"] = [{"path": entry["evidence"]["path"],
                                                "line": 2, "quote": "class PaymentController"}]
        path.write_text(json.dumps(overview), encoding="utf-8")
        result = self._run("validate", "--source", self.root, "--ir", path, "--strict-coverage")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("candidate", result.stdout + result.stderr)

    def test_one_controller_candidate_requires_all_its_route_anchors(self):
        (self.root / "src" / "PaymentController.java").write_text(
            '@RestController\nclass PaymentController {\n  @PostMapping("/payments")\n'
            '  void pay() {}\n  @GetMapping("/payments")\n  void list() {}\n}\n', encoding="utf-8")
        inventory, overview, path = self._fixture()
        entry = next(item for item in inventory["candidates"] if item["kind"] == "entrypoint")
        self.assertEqual(len(entry["members"]), 2)
        missing = self._run("validate", "--source", self.root, "--ir", path, "--strict-coverage")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("candidate source anchors", missing.stdout + missing.stderr)
        overview["elements"][0]["evidence"].append(
            {"path": "src/PaymentController.java", "line": 5, "quote": '@GetMapping("/payments")'})
        path.write_text(json.dumps(overview), encoding="utf-8")
        complete = self._run("validate", "--source", self.root, "--ir", path, "--strict-coverage")
        self.assertEqual(complete.returncode, 0, complete.stdout + complete.stderr)

    def test_malformed_decision_has_structured_error(self):
        _, overview, path = self._fixture()
        overview["coverage"]["decisions"][0]["candidateId"] = []
        path.write_text(json.dumps(overview), encoding="utf-8")
        result = self._run("validate", "--source", self.root, "--ir", path, "--strict-coverage")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(json.loads(result.stdout)["valid"])
        self.assertIn("candidateId", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_malformed_inventory_scope_has_structured_error(self):
        inventory, _, path = self._fixture()
        inventory["scopePaths"] = [{}]
        (self.root / "candidates.json").write_text(json.dumps(inventory), encoding="utf-8")
        result = self._run("validate", "--source", self.root, "--ir", path, "--strict-coverage")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid shape", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_malformed_manual_candidate_has_structured_error(self):
        _, overview, path = self._fixture()
        overview["coverage"]["manualCandidates"] = [
            {"id": "manual_invalid", "kind": "relationship", "evidence": None}]
        overview["coverage"]["decisions"].append(
            {"candidateId": "manual_invalid", "status": "overview", "element": "api"})
        path.write_text(json.dumps(overview), encoding="utf-8")
        result = self._run("validate", "--source", self.root, "--ir", path, "--strict-coverage")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(json.loads(result.stdout)["valid"])
        self.assertNotIn("Traceback", result.stderr)

    def test_manual_candidate_cannot_override_generated_member_shape(self):
        _, overview, path = self._fixture()
        overview["coverage"]["manualCandidates"] = [{
            "id": "manual_api", "kind": "relationship", "members": [{}],
            "evidence": {"path": "src/PaymentController.java", "line": 3,
                         "quote": '@PostMapping("/payments")'}}]
        overview["coverage"]["decisions"].append({
            "candidateId": "manual_api", "status": "overview", "element": "api"})
        path.write_text(json.dumps(overview), encoding="utf-8")
        result = self._run("validate", "--source", self.root, "--ir", path, "--strict-coverage")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_strict_scope_must_match_inventory_scope(self):
        _, overview, path = self._fixture()
        overview["scope"]["sourcePaths"] = ["src/service"]
        path.write_text(json.dumps(overview), encoding="utf-8")
        result = self._run("validate", "--source", self.root, "--ir", path, "--strict-coverage")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("scopePaths", result.stdout + result.stderr)

    def test_inventory_rejects_scope_without_source_files(self):
        with self.assertRaisesRegex(ValueError, "matched no source files"):
            discover_candidates(self.root, ["missing-module"])

    @unittest.skipUnless(shutil.which("drawio"), "official draw.io CLI is unavailable")
    def test_deliver_renders_overview_and_every_detail(self):
        _, _, path = self._fixture()
        output = self.root / "bundle"
        result = self._run("deliver", "--source", self.root, "--ir", path,
                           "--output", output, "--format", "drawio", "--export-for", "drawio:png",
                           "--svg-for", "drawio")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["coverageCheck"], "pass")
        self.assertEqual(receipt["geometryCheck"], "pass")
        self.assertEqual(receipt["coverageSummary"]["detail"], 1)
        self.assertTrue((output / "overview" / "architecture.drawio.png").is_file())
        self.assertTrue((output / "overview" / "architecture.drawio.svg").is_file())
        self.assertTrue((output / "details" / "cache-detail" / "architecture.drawio.png").is_file())
        self.assertTrue((output / "details" / "cache-detail" / "architecture.drawio.svg").is_file())
        self.assertTrue((output / "overview.json").is_file())
        self.assertTrue((output / "cache-detail.json").is_file())
        self.assertTrue((output / "candidates.json").is_file())

    @unittest.skipUnless(shutil.which("drawio") and shutil.which("false"),
                         "official draw.io CLI or false command is unavailable")
    def test_failed_replacement_preserves_last_complete_bundle(self):
        _, _, path = self._fixture()
        output = self.root / "bundle"
        command = ("deliver", "--source", self.root, "--ir", path,
                   "--output", output, "--format", "drawio", "--export-for", "drawio:png")
        first = self._run(*command)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        original = (output / "manifest.json").read_bytes()
        failed = self._run(*command, "--drawio-cli", shutil.which("false"))
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual((output / "manifest.json").read_bytes(), original)
        self.assertTrue((output / "details" / "cache-detail" / "architecture.drawio.png").is_file())

    def test_geometry_check_rejects_overlapping_cards(self):
        ir = {"title": "Layout", "scope": {"system": "Demo", "container": "Demo"},
              "elements": [{"id": "a", "type": "service", "name": "A", "description": "A"},
                           {"id": "b", "type": "service", "name": "B", "description": "B"}],
              "relations": []}
        xml = render_landscape(ir)
        self.assertEqual(check_landscape_geometry(xml), [])
        import xml.etree.ElementTree as ET
        tree = ET.fromstring(xml)
        cells = {cell.get("id"): cell for cell in tree.iter("mxCell")}
        cells["node_b"].find("mxGeometry").set("x", cells["node_a"].find("mxGeometry").get("x"))
        self.assertTrue(any("overlap" in problem for problem in
                            check_landscape_geometry(ET.tostring(tree, encoding="unicode"))))


if __name__ == "__main__":
    unittest.main()
