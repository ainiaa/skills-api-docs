import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from discovery import CLASS_KINDS, FakeEngine, NullEngine, select_engine
from generate_api_docs import controller_candidates, endpoint_selector_names, endpoint_source_file, heal_unresolved_roots, is_controller_file, package_root, qualified_name_matches


FAKE_ENV = "API_SAVIOR_FAKE_ENGINE"

CONTROLLER_SOURCE = '''
    package example;
    class Order { private String orderNo; public String getOrderNo() { return orderNo; }
        public void setOrderNo(String value) { this.orderNo = value; } }
    @RestController class OrderController {
        @PostMapping("/orders") Order createOrder(@RequestBody Order request) { return request; }
    }
'''

MAIN_SOURCE = '''
    package com.example.app;
    class Order { private com.example.common.Result result;
        public com.example.common.Result getResult() { return result; }
        public void setResult(com.example.common.Result value) { this.result = value; } }
    @RestController class OrderController {
        @PostMapping("/orders") Order createOrder(@RequestBody Order request) { return request; }
    }
'''

COMMON_SOURCE = '''
    package com.example.common;
    class Result { private String code; private String message; }
'''

SPLIT_SOURCE = '''
    package example;
    class Order { private String orderNo; public String getOrderNo() { return orderNo; }
        public void setOrderNo(String value) { this.orderNo = value; } }
'''
SPLIT_CONTROLLER_SOURCE = '''
    package example;
    @RestController class OrderController {
        @PostMapping("/orders") Order createOrder(@RequestBody Order request) { return request; }
    }
'''


def write_source(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def run_cli(arguments, env_extra=None):
    environment = dict(os.environ)
    environment.pop(FAKE_ENV, None)
    environment.update(env_extra or {})
    return subprocess.run([sys.executable, str(Path(__file__).with_name("generate_api_docs.py"))] + arguments,
                          capture_output=True, text=True, env=environment)


def manifest_for(locations: dict) -> str:
    manifest = {"locate": locations}
    handle = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(manifest, handle)
    handle.close()
    return handle.name


class PackageRootTest(unittest.TestCase):
    def test_package_declaration_derives_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_source(root, "com/example/common/Result.java", COMMON_SOURCE)
            self.assertEqual(root, package_root(source))

    def test_default_package_uses_parent_dir(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_source(root, "util/Loose.java", "class Loose { }")
            self.assertEqual(root / "util", package_root(source))

    def test_mismatched_package_returns_none(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_source(root, "elsewhere/Result.java", COMMON_SOURCE)
            self.assertIsNone(package_root(source))


class FakeEngineTest(unittest.TestCase):
    def test_locate_filters_by_kind_and_resolves_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_source(root, "com/example/Result.java", COMMON_SOURCE)
            engine = FakeEngine({"locate": {"Result": [
                {"path": str(source), "line": 3, "kind": "class", "name": "Result"},
                {"path": str(source), "line": 3, "kind": "method", "name": "Result"},
            ]}}, project_root=root)
            self.assertEqual([source.resolve()],
                             [location.path for location in engine.locate("Result", CLASS_KINDS)])
            self.assertEqual([], engine.locate("Missing", CLASS_KINDS))

    def test_select_engine_reads_fake_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "manifest.json"
            manifest_path.write_text(json.dumps({"locate": {}}), encoding="utf-8")
            saved = os.environ.get(FAKE_ENV)
            os.environ[FAKE_ENV] = str(manifest_path)
            try:
                engine = select_engine([Path(directory)])
            finally:
                if saved is None:
                    os.environ.pop(FAKE_ENV, None)
                else:
                    os.environ[FAKE_ENV] = saved
            self.assertIsInstance(engine, FakeEngine)
            self.assertTrue(engine.sync())


class ControllerCandidatesTest(unittest.TestCase):
    def test_annotated_files_are_candidates_and_missing_names_abort(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = write_source(root, "OrderController.java", SPLIT_CONTROLLER_SOURCE)
            plain = write_source(root, "Order.java", SPLIT_SOURCE)
            engine = FakeEngine({"locate": {
                "createOrder": [{"path": str(controller), "line": 4, "kind": "method", "name": "createOrder"}],
                "other": [{"path": str(plain), "line": 3, "kind": "method", "name": "other"}],
            }}, project_root=root)
            self.assertEqual([controller.resolve()], controller_candidates(engine, ["createOrder"]))
            self.assertIsNone(controller_candidates(engine, ["createOrder", "missing"]))

    def test_plain_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plain = write_source(root, "Order.java", SPLIT_SOURCE)
            engine = FakeEngine({"locate": {
                "createOrder": [{"path": str(plain), "line": 3, "kind": "method", "name": "createOrder"}],
            }}, project_root=root)
            self.assertIsNone(controller_candidates(engine, ["createOrder"]))


class HealRootsTest(unittest.TestCase):
    def test_unresolved_names_map_to_package_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_source(root, "com/example/common/Result.java", COMMON_SOURCE)
            engine = FakeEngine({"locate": {"Result": [
                {"path": str(source), "line": 3, "kind": "class", "name": "Result"}]}})
            additions = heal_unresolved_roots(engine, ["Result", "com.example.common.Result"], set())
            self.assertEqual([root.resolve()], sorted(additions, key=str))

    def test_known_roots_are_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = write_source(root, "com/example/common/Result.java", COMMON_SOURCE)
            engine = FakeEngine({"locate": {"Result": [
                {"path": str(source), "line": 3, "kind": "class", "name": "Result"}]}})
            self.assertEqual({}, heal_unresolved_roots(engine, ["Result"], {root.resolve()}))

    def test_qualified_names_filter_wrong_package_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            right = write_source(root, "right/com/example/common/Result.java", COMMON_SOURCE)
            wrong = write_source(root, "wrong/com/other/Result.java", COMMON_SOURCE)
            engine = FakeEngine({"locate": {"Result": [
                {"path": str(wrong), "line": 3, "kind": "class", "name": "Result",
                 "qualified_name": "com.other::Result"},
                {"path": str(right), "line": 3, "kind": "class", "name": "Result",
                 "qualified_name": "com.example.common::Result"},
            ]}})
            additions = heal_unresolved_roots(engine, ["com.example.common.Result"], set())
            self.assertEqual([right.parents[3].resolve()], sorted(additions, key=str))

    def test_qualified_name_matches_tolerates_separator_and_unknown(self):
        self.assertTrue(qualified_name_matches("com.example.common::Result", "com.example.common", "Result"))
        self.assertTrue(qualified_name_matches("", "com.example.common", "Result"))
        self.assertFalse(qualified_name_matches("com.other::Result", "com.example.common", "Result"))


class SourceHelperTest(unittest.TestCase):
    def test_endpoint_source_file_strips_trailing_line_only(self):
        self.assertEqual("/repo/a:b/OrderController.java", endpoint_source_file("/repo/a:b/OrderController.java:12"))
        self.assertEqual("/repo/OrderController.java", endpoint_source_file("/repo/OrderController.java"))

    def test_annotation_beyond_file_head_is_recognized(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            padded = "/* " + "x" * 9000 + " */\n" + SPLIT_CONTROLLER_SOURCE
            controller = write_source(root, "OrderController.java", padded)
            self.assertTrue(is_controller_file(controller))


class DiscoveryCliTest(unittest.TestCase):
    def test_endpoint_discovery_matches_full_scan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_source(root, "OrderController.java", CONTROLLER_SOURCE)
            full = run_cli(["--source", str(root), "--output", str(root / "full"), "--no-codegraph"])
            self.assertEqual(0, full.returncode, full.stderr)
            manifest = manifest_for({"createOrder": [
                {"path": str(root / "OrderController.java"), "line": 6, "kind": "method", "name": "createOrder"}]})
            narrowed = run_cli(["--source", str(root), "--endpoint", "createOrder",
                                "--output-file", str(root / "narrowed.md")], {FAKE_ENV: manifest})
            self.assertEqual(0, narrowed.returncode, narrowed.stderr)
            self.assertIn("[fake] narrowed scan to 1 controller file(s) for: createOrder", narrowed.stderr)
            self.assertEqual((root / "full/api-docs.md").read_text(encoding="utf-8"),
                             (root / "narrowed.md").read_text(encoding="utf-8"))

    def test_endpoint_discovery_falls_back_when_engine_misses(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_source(root, "OrderController.java", CONTROLLER_SOURCE)
            full = run_cli(["--source", str(root), "--output", str(root / "full")])
            manifest = manifest_for({})
            narrowed = run_cli(["--source", str(root), "--endpoint", "createOrder",
                                "--output-file", str(root / "narrowed.md")], {FAKE_ENV: manifest})
            self.assertEqual(0, narrowed.returncode, narrowed.stderr)
            self.assertNotIn("narrowed scan", narrowed.stderr)
            self.assertEqual((root / "full/api-docs.md").read_text(encoding="utf-8"),
                             (root / "narrowed.md").read_text(encoding="utf-8"))

    def test_unresolved_types_self_heal_from_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            main_root = write_source(root, "main/com/example/app/OrderController.java", MAIN_SOURCE).parents[3]
            common_root = write_source(root, "common/com/example/common/Result.java", COMMON_SOURCE).parents[3]
            manifest = manifest_for({"Result": [
                {"path": str(common_root / "com/example/common/Result.java"), "line": 3,
                 "kind": "class", "name": "Result"}]})
            healed = run_cli(["--source", str(main_root), "--output", str(root / "healed")], {FAKE_ENV: manifest})
            self.assertEqual(0, healed.returncode, healed.stderr)
            self.assertIn("[fake] auto-added source root", healed.stderr)
            healed_markdown = (root / "healed/api-docs.md").read_text(encoding="utf-8")
            self.assertIn("code", healed_markdown)
            both = run_cli(["--source", str(main_root), "--source", str(common_root),
                            "--output", str(root / "both"), "--no-codegraph"])
            self.assertEqual(0, both.returncode, both.stderr)
            self.assertEqual((root / "both/api-docs.md").read_text(encoding="utf-8"), healed_markdown)
            unhealed = run_cli(["--source", str(main_root), "--output", str(root / "unhealed"),
                                "--no-codegraph"])
            self.assertEqual(0, unhealed.returncode, unhealed.stderr)
            self.assertIn("Warning: unresolved DTO types", unhealed.stderr)
            self.assertNotIn("auto-added source root", unhealed.stderr)

    def test_no_codegraph_flag_disables_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_source(root, "main/com/example/app/OrderController.java", MAIN_SOURCE)
            common_root = write_source(root, "common/com/example/common/Result.java", COMMON_SOURCE).parents[3]
            manifest = manifest_for({"Result": [
                {"path": str(common_root / "com/example/common/Result.java"), "line": 3,
                 "kind": "class", "name": "Result"}]})
            disabled = run_cli(["--source", str(root / "main"), "--output", str(root / "out"),
                                "--no-codegraph"], {FAKE_ENV: manifest})
            self.assertEqual(0, disabled.returncode, disabled.stderr)
            self.assertNotIn("[fake]", disabled.stderr)
            self.assertIn("Warning: unresolved DTO types", disabled.stderr)

    def test_changed_regenerates_only_affected_endpoints(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            order = write_source(root, "Order.java", SPLIT_SOURCE)
            write_source(root, "OrderController.java", SPLIT_CONTROLLER_SOURCE)
            write_source(root, "Unrelated.java", "package example;\nclass Unrelated { }")
            manifest = manifest_for({"Order": [
                {"path": str(order), "line": 3, "kind": "class", "name": "Order"}]})
            changed_dto = run_cli(["--source", str(root), "--changed", str(order),
                                   "--output-file", str(root / "dto.md")], {FAKE_ENV: manifest})
            self.assertEqual(0, changed_dto.returncode, changed_dto.stderr)
            markdown = (root / "dto.md").read_text(encoding="utf-8")
            self.assertIn("createOrder", markdown)
            self.assertIn("orderNo", markdown)
            changed_controller = run_cli(["--source", str(root), "--changed", str(root / "OrderController.java"),
                                          "--output-file", str(root / "controller.md")], {FAKE_ENV: manifest})
            self.assertEqual(0, changed_controller.returncode, changed_controller.stderr)
            self.assertIn("createOrder", (root / "controller.md").read_text(encoding="utf-8"))
            unchanged = run_cli(["--source", str(root), "--changed", str(root / "Unrelated.java"),
                                 "--output-file", str(root / "empty.md")], {FAKE_ENV: manifest})
            self.assertEqual(0, unchanged.returncode, unchanged.stderr)
            self.assertIn("No endpoints affected by the changed files", unchanged.stdout)
            self.assertFalse((root / "empty.md").exists())

    def test_changed_locates_only_reachable_schemas(self):
        from generate_api_docs import affected_endpoints, scan_java_document
        order_source = '''
            package example;
            class Order { private String orderNo; public String getOrderNo() { return orderNo; }
                public void setOrderNo(String value) { this.orderNo = value; } }
        '''
        widget_source = '''
            package example;
            class Widget { private String tag; }
        '''
        controller_source = '''
            package example;
            @RestController class OrderController {
                @PostMapping("/orders") Order createOrder(@RequestBody Order request) { return request; }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            order = write_source(root, "Order.java", order_source)
            write_source(root, "Widget.java", widget_source)
            write_source(root, "OrderController.java", controller_source)
            document = scan_java_document([root])
            engine = FakeEngine({"locate": {
                "Order": [{"path": str(order), "line": 3, "kind": "class", "name": "Order"}],
                "Widget": [{"path": str(root / "Widget.java"), "line": 3, "kind": "class", "name": "Widget"}],
            }}, project_root=root)
            affected = affected_endpoints(document, engine, [order])
            self.assertEqual(["createOrder"], [item.name for item in affected])
            self.assertIn("Order", engine.locate_calls)
            self.assertNotIn("Widget", engine.locate_calls)

    def test_changed_output_dir_writes_all_three_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            order = write_source(root, "Order.java", SPLIT_SOURCE)
            write_source(root, "OrderController.java", SPLIT_CONTROLLER_SOURCE)
            manifest = manifest_for({"Order": [
                {"path": str(order), "line": 3, "kind": "class", "name": "Order"}]})
            run = run_cli(["--source", str(root), "--changed", str(order),
                           "--output", str(root / "out")], {FAKE_ENV: manifest})
            self.assertEqual(0, run.returncode, run.stderr)
            self.assertIn("createOrder", (root / "out/api-docs.md").read_text(encoding="utf-8"))
            collection = json.loads((root / "out/postman-collection.json").read_text(encoding="utf-8"))
            self.assertEqual(1, len(collection["item"]))
            self.assertIn("createOrder", (root / "out/curl.sh").read_text(encoding="utf-8"))

    def test_changed_requires_discovery_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_source(root, "OrderController.java", CONTROLLER_SOURCE)
            missing = run_cli(["--source", str(root), "--changed", str(root / "Order.java"),
                               "--output-file", str(root / "out.md"), "--no-codegraph"])
            self.assertNotEqual(0, missing.returncode)
            self.assertIn("requires a discovery engine", missing.stderr)

    def test_endpoint_selector_names_strip_route_and_client(self):
        self.assertEqual(["find"], endpoint_selector_names(["com.example.OrderClient#find@POST:/items"]))
        self.assertEqual(["find", "save"], endpoint_selector_names(["find@POST:/x", "save"]))


class NullEngineTest(unittest.TestCase):
    def test_source_files_walks_filesystem_and_locate_misses(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_source(root, "a/X.java", COMMON_SOURCE)
            write_source(root, "b/Y.txt", "not java")
            engine = NullEngine([root])
            self.assertEqual([root / "a/X.java"], engine.source_files(".java"))
            self.assertEqual([], engine.locate("Result", CLASS_KINDS))


try:
    import tree_sitter  # noqa: F401
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False

PYTHON_SOURCE = '''
    package_marker = None

    class OrderModel:
        def inflate(self):
            return None

    def build_order():
        return OrderModel()
'''


@unittest.skipUnless(TREE_SITTER_AVAILABLE, "tree-sitter packages not installed")
class TreeSitterEngineTest(unittest.TestCase):
    def test_locates_java_and_python_symbols_with_kind_filter(self):
        from tree_sitter_engine import create_engine
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            java_file = write_source(root, "com/example/OrderController.java", SPLIT_CONTROLLER_SOURCE)
            enum_source = '''
                package example;
                enum State { READY, BUSY }
                interface Handler { void handle(); }
            '''
            state_file = write_source(root, "com/example/State.java", enum_source)
            python_file = write_source(root, "com/example/orders.py", PYTHON_SOURCE)
            engine = create_engine([root])
            self.assertIsNotNone(engine)
            self.assertTrue(engine.sync())

            located = engine.locate("OrderController", CLASS_KINDS)
            self.assertEqual([(java_file.resolve(), "class")],
                             [(item.path, item.kind) for item in located])
            self.assertEqual("example", located[0].qualified_name)
            self.assertEqual([state_file.resolve()],
                             [item.path for item in engine.locate("State", CLASS_KINDS)
                              if item.kind == "enum"])
            self.assertEqual([python_file.resolve()],
                             [item.path for item in engine.locate("build_order", ("function", "method"))])
            self.assertEqual([java_file.resolve()],
                             [item.path for item in engine.locate("createOrder", ("function", "method"))])
            self.assertEqual([], engine.locate("OrderController", ("function", "method")))
            self.assertEqual([], engine.locate("DoesNotExist", CLASS_KINDS))
            self.assertEqual(sorted([java_file.resolve(), state_file.resolve()], key=str),
                             engine.source_files(".java"))
            self.assertEqual([], engine.source_files(".nonexistent"))

    def test_locate_expands_to_project_root_for_types_outside_roots(self):
        from tree_sitter_engine import create_engine
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            write_source(root, "main/com/example/app/OrderController.java", MAIN_SOURCE)
            common_root = root / "common"
            result_file = write_source(common_root, "com/example/common/Result.java", COMMON_SOURCE)
            engine = create_engine([root / "main"])
            located = engine.locate("Result", CLASS_KINDS)
            self.assertEqual([result_file.resolve()],
                             [item.path for item in located])
            self.assertEqual("com.example.common", located[0].qualified_name)

    def test_python_symbols_locate_without_package(self):
        from tree_sitter_engine import create_engine
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_source(root, "orders.py", PYTHON_SOURCE)
            engine = create_engine([root])
            located = engine.locate("OrderModel", CLASS_KINDS)
            self.assertEqual(["class"], [item.kind for item in located])
            self.assertEqual("", located[0].qualified_name)


if __name__ == "__main__":
    unittest.main()
