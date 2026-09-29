import contextlib
import io
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from api_document_ir import ApiDocument, Schema
from generate_api_docs import Endpoint, Field, example_for, gradle_modules, parse_class_from_jar, parse_classes, parse_endpoints, render_curl, render_markdown, render_postman, scan_java_document, unresolved_types
from python_fastapi_adapter import module_name, scan_python_document


class ParseEndpointsTest(unittest.TestCase):
    def test_cli_generates_aligned_markdown_postman_and_curl(self):
        source = '''
            package example;
            enum State { READY(7, "可用"); private final int code; private final String description;
                State(int code, String description) { this.code = code; this.description = description; }
            }
            class Request { @Schema(implementation = State.class) private int state; }
            @RestController class DemoController {
                @PostMapping("/save") void save(@RequestBody Request request) { }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Path(root, "DemoController.java").write_text(source, encoding="utf-8")
            output = root / "generated"
            subprocess.run([sys.executable, str(Path(__file__).with_name("generate_api_docs.py")),
                            "--source", str(root), "--output", str(output)], check=True, capture_output=True)
            markdown = (output / "api-docs.md").read_text(encoding="utf-8")
            collection = json.loads((output / "postman-collection.json").read_text(encoding="utf-8"))
            curl = (output / "curl.sh").read_text(encoding="utf-8")
        self.assertIn('"state": 7', markdown)
        self.assertIn("| READY | 7 | 可用 |", markdown)
        self.assertEqual(7, json.loads(collection["item"][0]["request"]["body"]["raw"])["state"])
        self.assertIn('"state": 7', curl)

    def test_java_examples_follow_plugin_field_meaning_and_numeric_rules(self):
        source = '''
            package example;
            class Request {
                /** 资产编码（唯一） */ private String assetCode;
                @Min(2) private int quantity;
                /** 变更时间 毫秒 */ private long changeTime;
                @Schema(example = "5") private int explicit;
            }
            @RestController class DemoController {
                @PostMapping("/save") void save(@RequestBody Request request) { }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "DemoController.java").write_text(source, encoding="utf-8")
            document = scan_java_document([Path(directory)])
        markdown = render_markdown(document, "")
        self.assertIn('"assetCode": "<资产编码>"', markdown)
        self.assertIn('"quantity": 2', markdown)
        self.assertIn("最小值为 2", markdown)
        self.assertIn('"changeTime": 1700000000000', markdown)
        self.assertIn('"explicit": 5', markdown)
        self.assertIn('"quantity": 2', render_postman(document, "")["item"][0]["request"]["body"]["raw"])

    def test_schema_minimum_keeps_generated_examples_within_integer_constraints(self):
        source = '''
            package example;
            class Request {
                @Schema(minimum = "1") private int quantity;
                @Min(2) @Schema(minimum = "3") private int stricter;
                @Schema(minimum = "invalid") private int unknown;
            }
            @RestController class DemoController {
                @PostMapping("/save") void save(@RequestBody Request request) { }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "DemoController.java").write_text(source, encoding="utf-8")
            document = scan_java_document([Path(directory)])
        expected = {'quantity': 1, 'stricter': 3, 'unknown': 0}
        markdown = render_markdown(document, "")
        postman = render_postman(document, "")["item"][0]["request"]["body"]["raw"]
        curl = render_curl(document, "")
        self.assertEqual(expected, json.loads(postman))
        for name, value in expected.items():
            self.assertIn(f'"{name}": {value}', markdown)
            self.assertIn(f'"{name}": {value}', curl)
        self.assertIn("最小值为 1", markdown)
        self.assertIn("最小值为 3", markdown)

    def test_json_property_and_request_param_names_are_used_on_wire(self):
        source = '''
            package example;
            class Request { @JsonProperty("asset_code") private String assetCode; }
            @RestController class DemoController {
                @PostMapping("/save") void save(@RequestBody Request request,
                    @RequestParam(name = "tenant_id", required = true) String tenantId) { }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "DemoController.java").write_text(source, encoding="utf-8")
            document = scan_java_document([Path(directory)])
        markdown = render_markdown(document, "")
        self.assertIn('"asset_code": "<assetCode>"', markdown)
        self.assertIn("| asset_code", markdown)
        self.assertIn("/save?tenant_id=<tenantId>", markdown)
        self.assertIn("tenant_id=<tenantId>", render_postman(document, "")["item"][0]["request"]["url"])
        self.assertIn("tenant_id=<tenantId>", render_curl(document, ""))

    def test_non_json_parameters_render_plugin_bulk_edit_and_query_values(self):
        source = '''
            package example;
            @RestController class DemoController {
                /** 查询
                 * @param code 资产编码
                 */
                @GetMapping("/items") void find(@RequestParam(required = true) String code,
                                                 @RequestParam(required = false) int page) { }
                @PostMapping("/submit") void submit(@RequestParam(required = true) String code) { }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "DemoController.java").write_text(source, encoding="utf-8")
            document = scan_java_document([Path(directory)])
        markdown = render_markdown(document, "")
        self.assertIn("### 入参示例 (Postman Bulk Edit)", markdown)
        self.assertIn("code:<资产编码>", markdown)
        self.assertIn("//page:0", markdown)
        self.assertIn("/items?code=<资产编码>&page=0", markdown)
        self.assertIn("/submit", markdown)
        get_request = render_postman(document, "")["item"][0]["request"]
        self.assertEqual("<资产编码>", get_request["url"]["query"][0]["value"])
        self.assertIn("code=<资产编码>", render_curl(document, ""))

    def test_request_param_defaults_to_required_like_plugin(self):
        source = '''
            package example;
            @RestController class DemoController {
                @GetMapping("/find") void find(@RequestParam String code) { }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "DemoController.java").write_text(source, encoding="utf-8")
            document = scan_java_document([Path(directory)])
        markdown = render_markdown(document, "")
        self.assertIn("code:<code>", markdown)
        self.assertNotIn("//code:<code>", markdown)

    def test_api_response_annotations_render_code_table(self):
        source = '''
            package example;
            @RestController class DemoController {
                @ApiResponses({@ApiResponse(code = 400, message = "参数错误"),
                               @ApiResponse(code = 404, message = "不存在")})
                @GetMapping("/status") void status() { }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "DemoController.java").write_text(source, encoding="utf-8")
            document = scan_java_document([Path(directory)])
        markdown = render_markdown(document, "")
        self.assertIn("| **400** | 参数错误 |", markdown)
        self.assertIn("| **404** | 不存在 |", markdown)

    def test_unresolved_request_body_does_not_render_empty_object_example(self):
        document = scan_java_document_from_values([Endpoint(
            "save", "保存", "POST", "/save", [], Field("request", "MissingDto"),
            "void", "Demo.java:1", "application/json")], {})
        markdown = render_markdown(document, "")
        self.assertIn("请求体类型 MissingDto 未解析", markdown)
        self.assertNotIn("```json\n{}", markdown)
        self.assertNotIn("body", render_postman(document, "")["item"][0]["request"])
        self.assertNotIn("--data", render_curl(document, ""))

    def test_method_notes_and_response_codes_follow_plugin_sections(self):
        source = '''
            package example;
            @RestController class DemoController {
                /** 查询状态
                 * @notes 仅供内部使用
                 * @code 400 参数错误
                 */
                @GetMapping("/status") void status() { }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "DemoController.java").write_text(source, encoding="utf-8")
            document = scan_java_document([Path(directory)])
        markdown = render_markdown(document, "")
        self.assertIn("# 查询状态\n> 仅供内部使用", markdown)
        self.assertIn("## 更多信息", markdown)
        self.assertIn("| **400** | 参数错误 |", markdown)

    def test_enum_usage_through_helper_method_is_attached_to_request_field(self):
        source = '''
            package example;
            enum State {
                WAITING(10, "等待"), DONE(20, "完成");
                private final int code; private final String description;
                State(int code, String description) { this.code = code; this.description = description; }
                static State fromCode(int code) { return WAITING; }
            }
            class Request { private int state; int getState() { return state; } }
            @RestController class DemoController {
                @PostMapping("/save") void save(@RequestBody Request request) { validate(request); }
                void validate(Request value) { State.fromCode(value.getState()); }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "DemoController.java").write_text(source, encoding="utf-8")
            document = scan_java_document([Path(directory)])
        markdown = render_markdown(document, "")
        self.assertIn('"state": 10', markdown)
        self.assertIn("### 入参 state", markdown)
        self.assertIn("| WAITING | 10 | 等待 |", markdown)

    def test_enum_method_parameter_selects_wire_property_without_leaking_to_other_endpoint(self):
        source = '''
            package example;
            enum State {
                WAITING(10, "waiting"), DONE(20, "done");
                private final int code; private final String label;
                State(int code, String label) { this.code = code; this.label = label; }
                static State fromLabel(String label) { return WAITING; }
            }
            class Request { private String state; String getState() { return state; } }
            @RestController class DemoController {
                @PostMapping("/mapped") void mapped(@RequestBody Request request) {
                    State.fromLabel(request.getState());
                }
                @PostMapping("/plain") void plain(@RequestBody Request request) { }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "DemoController.java").write_text(source, encoding="utf-8")
            document = scan_java_document([Path(directory)])
        markdown = render_markdown(document, "")
        mapped, plain = markdown.split("# plain", 1)
        self.assertIn('"state": "waiting"', mapped)
        self.assertIn("| WAITING | waiting |", mapped)
        self.assertNotIn("## 枚举说明", plain)

    def test_conflicting_enum_method_uses_do_not_guess(self):
        source = '''
            package example;
            enum State { WAITING(10); private final int code;
                State(int code) { this.code = code; }
                static State fromCode(int code) { return WAITING; }
            }
            enum Mode { AUTO(20); private final int code;
                Mode(int code) { this.code = code; }
                static Mode fromCode(int code) { return AUTO; }
            }
            class Request { private int value; int getValue() { return value; } }
            @RestController class DemoController {
                @PostMapping("/save") void save(@RequestBody Request request) {
                    State.fromCode(request.getValue()); Mode.fromCode(request.getValue());
                }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "DemoController.java").write_text(source, encoding="utf-8")
            document = scan_java_document([Path(directory)])
        markdown = render_markdown(document, "")
        self.assertIn('"value": 0', markdown)
        self.assertNotIn("## 枚举说明", markdown)

    def test_enum_inference_does_not_leak_between_parameters_of_same_dto_type(self):
        source = '''
            package example;
            enum State { WAITING(10); private final int code;
                State(int code) { this.code = code; }
                static State fromCode(int code) { return WAITING; }
            }
            class Request { private int state; int getState() { return state; } }
            @RestController class DemoController {
                @PostMapping("/save") void save(Request first, Request second) {
                    State.fromCode(first.getState());
                }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "DemoController.java").write_text(source, encoding="utf-8")
            document = scan_java_document([Path(directory)])
        markdown = render_markdown(document, "")
        self.assertIn("first.state:10", markdown)
        self.assertIn("second.state:0", markdown)

    def test_java_enum_request_body_keeps_inline_values_and_renders_enum_table(self):
        source = '''
            package example;
            enum State {
                /** 等待 */ WAITING(10, "等待", "gray"),
                /** 完成 */ DONE(20, "完成", "green");
                @JsonValue private final int code;
                private final String description;
                private final String color;
                State(int code, String description, String color) {
                    this.code = code; this.description = description; this.color = color;
                }
            }
            class Request { /** 状态 */ private State state; private String name; }
            @RestController class DemoController {
                @PostMapping("/save") void save(@RequestBody Request request) { }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "DemoController.java").write_text(source, encoding="utf-8")
            document = scan_java_document([Path(directory)])
        markdown = render_markdown(document, "")
        self.assertIn('"state": 10', markdown)
        self.assertIn('"name": "<name>"', markdown)
        self.assertIn("WAITING（10：等待", markdown)
        self.assertIn("## 枚举说明", markdown)
        self.assertIn("| WAITING | 10 | 等待 | color=gray |", markdown)
        self.assertIn('"state": 10', render_postman(document, "")["item"][0]["request"]["body"]["raw"])
        self.assertIn('"state": 10', render_curl(document, ""))

    def test_scalar_field_can_reference_enum_with_annotation_class_literal(self):
        source = '''
            package example;
            enum State {
                WAITING(10, "等待"), DONE(20, "完成");
                private final int code;
                private final String description;
                State(int code, String description) { this.code = code; this.description = description; }
            }
            class Request { @Schema(implementation = State.class) private Integer state; }
            @RestController class DemoController {
                @PostMapping("/save") void save(@RequestBody Request request) { }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "DemoController.java").write_text(source, encoding="utf-8")
            document = scan_java_document([Path(directory)])
        markdown = render_markdown(document, "")
        self.assertIn('"state": 10', markdown)
        self.assertIn("| WAITING | 10 | 等待 | - |", markdown)
        self.assertIn("10：等待", markdown)

    def test_incompatible_enum_value_uses_declared_scalar_placeholder(self):
        source = '''
            package example;
            enum State { WAITING("waiting"); private final String code;
                State(String code) { this.code = code; }
            }
            class Request { @Schema(implementation = State.class) private int state; }
            @RestController class DemoController {
                @PostMapping("/save") void save(@RequestBody Request request) { }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "DemoController.java").write_text(source, encoding="utf-8")
            document = scan_java_document([Path(directory)])
        self.assertIn('"state": 0', render_markdown(document, ""))

    def test_enum_with_unresolved_wire_value_does_not_invent_one(self):
        source = '''
            package example;
            enum State { WAITING(10), DONE(20); private final int code;
                State(int code) { this.code = code; }
                @JsonValue int getWire() { return transform(code); }
            }
            class Request { private State state; }
            @RestController class DemoController {
                @PostMapping("/save") void save(@RequestBody Request request) { }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "DemoController.java").write_text(source, encoding="utf-8")
            document = scan_java_document([Path(directory)])
        markdown = render_markdown(document, "")
        self.assertIn("取值未解析", markdown)
        self.assertNotIn('"state": "WAITING"', markdown)
        self.assertIn('"state": "<state>"', markdown)

    def test_renamed_enum_members_use_serialized_value_in_response(self):
        source = '''
            package example;
            enum State { @JsonProperty("waiting") WAITING, @SerializedName("done") DONE }
            class Response { private State state; }
            @RestController class DemoController {
                @GetMapping("/status") Response status() { return null; }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "DemoController.java").write_text(source, encoding="utf-8")
            document = scan_java_document([Path(directory)])
        markdown = render_markdown(document, "")
        self.assertIn('"state": "waiting"', markdown)
        self.assertIn("| WAITING | waiting |", markdown)
        self.assertIn("| DONE | done |", markdown)

    def test_enum_extra_properties_are_preserved_for_direct_and_linked_fields(self):
        source = '''
            package example;
            enum State {
                WAITING(10, "等待", "gray"), DONE(20, "完成", "green");
                private final int code; private final String description; private final String color;
                State(int code, String description, String color) {
                    this.code = code; this.description = description; this.color = color;
                }
            }
            class Response { private State state; @Schema(implementation = State.class) private int stateCode; }
            @RestController class DemoController {
                @GetMapping("/status") Response status() { return null; }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "DemoController.java").write_text(source, encoding="utf-8")
            document = scan_java_document([Path(directory)])
        markdown = render_markdown(document, "")
        self.assertIn("| WAITING | WAITING | 等待 | code=10；color=gray |", markdown)
        self.assertIn("| WAITING | 10 | 等待 | color=gray |", markdown)

    def test_json_value_method_returning_enum_field_is_resolved(self):
        source = '''
            package example;
            enum State {
                WAITING("w"), DONE("d");
                private final String wire;
                State(String wire) { this.wire = wire; }
                @JsonValue String serialize() { return this.wire; }
            }
            class Request { private State state; }
            @RestController class DemoController {
                @PostMapping("/save") void save(@RequestBody Request request) { }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "DemoController.java").write_text(source, encoding="utf-8")
            document = scan_java_document([Path(directory)])
        self.assertIn('"state": "w"', render_markdown(document, ""))

    def test_python_fastapi_adapter_produces_same_ir(self):
        source = '''
            from fastapi import FastAPI
            from pydantic import BaseModel
            app = FastAPI()
            class CreateUser(BaseModel):
                name: str
            class User(BaseModel):
                id: int
            @app.post("/users")
            async def create_user(payload: CreateUser) -> User:
                return User(id=1)
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "api.py").write_text(textwrap.dedent(source), encoding="utf-8")
            document = scan_python_document([Path(directory)])
        self.assertEqual("python", document.language)
        self.assertEqual("fastapi", document.framework)
        self.assertEqual("/users", document.endpoints[0].path)
        self.assertEqual("CreateUser", document.endpoints[0].request_body.type_name)
        self.assertIn("python:api.CreateUser", document.schemas)

    def test_python_fastapi_resolves_imported_model_and_router_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Path(root, "models.py").write_text("from pydantic import BaseModel\nclass CreateUser(BaseModel):\n    name: str\n", encoding="utf-8")
            Path(root, "api.py").write_text(textwrap.dedent('''
                from fastapi import APIRouter, Path
                from models import CreateUser
                router = APIRouter(prefix="/v1")
                @router.post("/users")
                def create(payload: CreateUser, user_id: int = Path(...)):
                    return None
            '''), encoding="utf-8")
            document = scan_python_document([root])
        endpoint = document.endpoints[0]
        self.assertEqual("/v1/users", endpoint.path)
        self.assertEqual("python:models.CreateUser", endpoint.request_body.schema_id)
        self.assertEqual("path", endpoint.parameters[0].location)

    def test_python_fastapi_resolves_included_router_response_model_and_depends(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Path(root, "models.py").write_text("from pydantic import BaseModel\nclass User(BaseModel):\n    id: int\n", encoding="utf-8")
            Path(root, "routes.py").write_text(textwrap.dedent('''
                from fastapi import APIRouter, Depends, Path
                from models import User
                router = APIRouter(prefix="/users")
                def current_user(): return None
                @router.get("/{user_id}", response_model=User)
                def get_user(user_id: int = Path(...), user=Depends(current_user)):
                    return None
            '''), encoding="utf-8")
            Path(root, "app.py").write_text(textwrap.dedent('''
                from fastapi import FastAPI
                from routes import router
                app = FastAPI()
                app.include_router(router, prefix="/v1")
            '''), encoding="utf-8")
            document = scan_python_document([root])
        endpoint = document.endpoints[0]
        self.assertEqual("/v1/users/{user_id}", endpoint.path)
        self.assertEqual("User", endpoint.response_type)
        self.assertEqual("python:models.User", endpoint.response_schema_id)
        self.assertEqual(["user_id"], [field.name for field in endpoint.parameters])

    def test_python_fastapi_resolves_relative_model_import(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Path(root, "app").mkdir()
            Path(root, "app", "models.py").write_text("from pydantic import BaseModel\nclass User(BaseModel):\n    id: int\n", encoding="utf-8")
            Path(root, "other.py").write_text("from pydantic import BaseModel\nclass User(BaseModel):\n    code: str\n", encoding="utf-8")
            Path(root, "app", "routes.py").write_text(textwrap.dedent('''
                from fastapi import APIRouter
                from .models import User
                router = APIRouter()
                @router.get("/users", response_model=User)
                def users(): return None
            '''), encoding="utf-8")
            document = scan_python_document([root])
        self.assertEqual("python:app.models.User", document.endpoints[0].response_schema_id)

    def test_python_fastapi_marks_marker_defaults_as_required(self):
        source = '''
            from fastapi import FastAPI, Query
            app = FastAPI()
            @app.get("/users")
            def users(query: str = Query()): return None
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "api.py").write_text(textwrap.dedent(source), encoding="utf-8")
            document = scan_python_document([Path(directory)])
        self.assertTrue(document.endpoints[0].parameters[0].required)

    def test_python_fastapi_supports_module_imports_and_callable_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Path(root, "app").mkdir()
            Path(root, "app", "models.py").write_text("from pydantic import BaseModel\nclass User(BaseModel):\n    id: int\n", encoding="utf-8")
            Path(root, "app", "routes.py").write_text(textwrap.dedent('''
                from fastapi import APIRouter
                from . import models
                router = APIRouter()
                def default_limit(): return 10
                @router.get("/users", response_model=models.User)
                def users(limit: int = default_limit()): return None
            '''), encoding="utf-8")
            document = scan_python_document([root])
        self.assertEqual("python:app.models.User", document.endpoints[0].response_schema_id)
        self.assertFalse(document.endpoints[0].parameters[0].required)
    def test_java_adapter_produces_language_neutral_document(self):
        source = '''
            package example.api;
            class Request { private String code; }
            @RestController
            class DemoController {
                @PostMapping("/query")
                Response query(@RequestBody Request request) { return null; }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "DemoController.java").write_text(source, encoding="utf-8")
            document = scan_java_document([Path(directory)])
        self.assertEqual(1, document.ir_version)
        self.assertEqual("java", document.language)
        self.assertEqual("spring", document.framework)
        self.assertIn("java:example.api.Request", document.schemas)

    def test_keeps_same_named_schemas_separate(self):
        source_a = '''package first; class Request { private String first; }'''
        source_b = '''package second; class Request { private String second; }'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Path(root, "First.java").write_text(source_a, encoding="utf-8")
            Path(root, "Second.java").write_text(source_b, encoding="utf-8")
            document = scan_java_document([root])
        self.assertIn("java:first.Request", document.schemas)
        self.assertIn("java:second.Request", document.schemas)
        self.assertNotIn("Request", document.classes())

    def test_resolves_imported_schema_id_without_changing_type_label(self):
        request = '''package contract; class Request { private String code; }'''
        controller = '''
            package api;
            import contract.Request;
            @RestController
            class DemoController {
                @PostMapping("/query")
                Response query(@RequestBody Request request) { return null; }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Path(root, "Request.java").write_text(request, encoding="utf-8")
            Path(root, "DemoController.java").write_text(controller, encoding="utf-8")
            document = scan_java_document([root])
        self.assertEqual("Request", document.endpoints[0].request_body.type_name)
        self.assertEqual("java:contract.Request", document.endpoints[0].request_body.schema_id)

    def test_resolves_nested_java_schema_by_qualified_name(self):
        source = '''
            package example;
            class One { static class Request { private String first; } }
            class Two { static class Request { private String second; } }
            @RestController class DemoController {
                @PostMapping("/save") void save(@RequestBody One.Request request) { }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "DemoController.java").write_text(source, encoding="utf-8")
            document = scan_java_document([Path(directory)])
        self.assertIn("java:example.One.Request", document.schemas)
        self.assertIn("java:example.Two.Request", document.schemas)
        self.assertEqual("java:example.One.Request", document.endpoints[0].request_body.schema_id)

    def test_resolves_collection_element_schema_id(self):
        source = '''
            package example;
            class Item { private String code; }
            @RestController class DemoController {
                @PostMapping("/items") void save(@RequestBody List<Item> items) { }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "DemoController.java").write_text(source, encoding="utf-8")
            document = scan_java_document([Path(directory)])
        self.assertEqual("java:example.Item", document.endpoints[0].request_body.schema_id)

    def test_renderer_uses_schema_id_when_names_collide(self):
        from api_document_ir import ApiDocument, Schema
        document = ApiDocument(1, "java", "spring", [Endpoint("save", "保存", "POST", "/save", [],
            Field("request", "Request", schema_id="java:second.Request"), "void", "Demo.java:1")], {
            "java:first.Request": Schema("java:first.Request", "Request", "first.Request", "", [Field("first", "String")]),
            "java:second.Request": Schema("java:second.Request", "Request", "second.Request", "", [Field("second", "String")]),
        })
        self.assertIn('"second": "<second>"', render_markdown(document, ""))

    def test_renderer_uses_schema_id_for_generic_request_and_response(self):
        from api_document_ir import ApiDocument, Schema
        document = ApiDocument(1, "java", "spring", [Endpoint(
            "save", "保存", "POST", "/save", [],
            Field("items", "List<Item>", schema_id="java:second.Item"), "Response",
            "Demo.java:1", response_schema_id="java:second.Response"
        )], {
            "java:first.Item": Schema("java:first.Item", "Item", "first.Item", "", [Field("first", "String")]),
            "java:second.Item": Schema("java:second.Item", "Item", "second.Item", "", [Field("second", "String")]),
            "java:first.Response": Schema("java:first.Response", "Response", "first.Response", "", [Field("first", "String")]),
            "java:second.Response": Schema("java:second.Response", "Response", "second.Response", "", [Field("second", "String")]),
        })
        markdown = render_markdown(document, "")
        self.assertIn('"second": "<second>"', markdown)
        self.assertNotIn('"first": "<first>"', markdown)

    def test_renderer_resolves_nested_generic_schema_ids(self):
        from api_document_ir import ApiDocument, Schema
        document = ApiDocument(1, "java", "spring", [Endpoint(
            "query", "查询", "POST", "/query", [], None, "Wrapper<second.Page<second.Response>>",
            "Demo.java:1", response_schema_id="java:wrapper.Wrapper"
        )], {
            "java:wrapper.Wrapper": Schema("java:wrapper.Wrapper", "Wrapper", "wrapper.Wrapper", "", [Field("data", "T")]),
            "java:first.Page": Schema("java:first.Page", "Page", "first.Page", "", [Field("first", "String")]),
            "java:second.Page": Schema("java:second.Page", "Page", "second.Page", "", [Field("records", "List<T>")]),
            "java:first.Response": Schema("java:first.Response", "Response", "first.Response", "", [Field("first", "String")]),
            "java:second.Response": Schema("java:second.Response", "Response", "second.Response", "", [Field("second", "String")]),
        })
        markdown = render_markdown(document, "")
        self.assertIn('"records": [', markdown)
        self.assertIn('"second": "<second>"', markdown)
        self.assertNotIn('"first": "<first>"', markdown)

    def test_curl_get_uses_query_string_mode(self):
        endpoint = Endpoint("find", "查询", "GET", "/items", [Field("code", "String", location="query")], None, "void", "Demo.java:1")
        self.assertIn("/items?code=<code>", render_curl(scan_java_document_from_values([endpoint], {}), ""))

    def test_parses_package_private_mapped_method(self):
        source = '''
            @RestController
            @RequestMapping("/v2")
            class DemoController {
                /** 查询 */
                @PostMapping(value = "/page")
                ResponseBaseVo<BasePageResponseVO<Response>> query(@RequestBody Request request) {
                    return null;
                }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "DemoController.java").write_text(source, encoding="utf-8")
            endpoints = parse_endpoints([Path(directory)])
        self.assertEqual(1, len(endpoints))
        self.assertEqual("query", endpoints[0].name)
        self.assertEqual("查询", endpoints[0].notes)
        self.assertEqual("POST", endpoints[0].method)
        self.assertEqual("/v2/page", endpoints[0].path)
        self.assertEqual("Request", endpoints[0].request_body.type_name)
        self.assertEqual("ResponseBaseVo<BasePageResponseVO<Response>>", endpoints[0].response_type)

    def test_parses_feign_client_path_and_endpoint(self):
        source = '''
            @FeignClient(name = "base", path = "/manage/contact")
            interface ContactClient {
                @PostMapping("/query")
                Response query(@RequestBody Request request);
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "ContactClient.java").write_text(source, encoding="utf-8")
            endpoints = parse_endpoints([Path(directory)])
        self.assertEqual(1, len(endpoints))
        self.assertEqual("/manage/contact/query", endpoints[0].path)

    def test_parses_composed_mapping_and_feign_class_mapping(self):
        source = '''
            @RequestMapping(method = RequestMethod.POST)
            @interface CreateMapping { String[] value() default {}; }
            @FeignClient(name = "base", path = "/manage")
            @RequestMapping("/contact")
            interface ContactClient {
                @CreateMapping("/create")
                void create(@RequestBody Request request);
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "ContactClient.java").write_text(source, encoding="utf-8")
            endpoint = parse_endpoints([Path(directory)])[0]
        self.assertEqual("POST", endpoint.method)
        self.assertEqual("/manage/contact/create", endpoint.path)

    def test_does_not_document_method_local_variables_as_dto_fields(self):
        source = '''
            class Request {
                private String code;
                void helper() { String leaked = "not a field"; }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "Request.java").write_text(source, encoding="utf-8")
            classes = parse_classes([Path(directory)])
        self.assertEqual(["code"], [item.name for item in classes["Request"]])

    def test_renders_request_parameters_as_form_data_and_omits_void_response_fields(self):
        source = '''
            @RestController
            class DemoController {
                @PostMapping("/submit")
                void submit(@RequestParam String code) { }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "DemoController.java").write_text(source, encoding="utf-8")
            endpoint = parse_endpoints([Path(directory)])[0]
        self.assertEqual("application/x-www-form-urlencoded", endpoint.content_type)
        document = scan_java_document_from_values([endpoint], {})
        self.assertEqual("urlencoded", render_postman(document, "")["item"][0]["request"]["body"]["mode"])
        self.assertNotIn("| return     |", render_markdown(document, ""))

    def test_includes_inherited_request_and_response_wrapper_fields(self):
        source = '''
            class BaseRequest { private String appname; }
            class Request extends BaseRequest { private String code; }
            class Response { private String id; }
            class BasePageResponseVO<T> { private List<T> records; }
            class ResponseBaseVo<T> { private T data; }
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "Models.java").write_text(source, encoding="utf-8")
            classes = parse_classes([Path(directory)])
        self.assertEqual(["appname", "code"],
                         [item.name for item in classes["Request"]])
        response = example_for("ResponseBaseVo<BasePageResponseVO<Response>>", classes)
        self.assertEqual("HelloWorld", response["data"]["records"][0]["id"])

    def test_resolves_each_generic_specialization_independently(self):
        from api_document_ir import ApiDocument, Schema
        document = ApiDocument(1, "java", "spring", [], {
            "java:Box": Schema("java:Box", "Box", "Box", "", [Field("value", "T")], type_parameters=["T"]),
            "java:First": Schema("java:First", "First", "First", "", [Field("first", "String")]),
            "java:Second": Schema("java:Second", "Second", "Second", "", [Field("second", "String")]),
        }).normalized()
        first = document.fields_for_type(document.type_ref(Field("first", "Box<First>", schema_id="java:Box")))
        second = document.fields_for_type(document.type_ref(Field("second", "Box<Second>", schema_id="java:Box")))
        self.assertEqual("First", first[0].type_ref.name)
        self.assertEqual("Second", second[0].type_ref.name)

    def test_resolves_generic_parent_binding_and_map_values(self):
        source = '''
            class Payload { private String id; }
            class Base<T> { private T data; }
            class Request extends Base<Payload> { private Map<String, Payload> indexed; }
            @RestController class DemoController {
                @PostMapping("/save") void save(@RequestBody Request request) { }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "DemoController.java").write_text(source, encoding="utf-8")
            document = scan_java_document([Path(directory)])
        fields = document.fields_for_type(document.type_ref(document.endpoints[0].request_body))
        self.assertEqual("Payload", fields[0].type_ref.name)
        self.assertEqual("java:Payload", fields[1].type_ref.arguments[1].schema_id)
        self.assertIn('"indexed": {', render_markdown(document, ""))
        self.assertIn('"id": "<id>"', render_markdown(document, ""))

    def test_resolves_media_type_constant_and_kotlin_gradle_modules(self):
        source = '''
            @RestController class DemoController {
                @PostMapping(value = "/save", consumes = MediaType.APPLICATION_JSON_VALUE)
                void save(@RequestBody String request) { }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Path(root, "settings.gradle.kts").write_text("", encoding="utf-8")
            Path(root, "app", "src/main/java").mkdir(parents=True)
            controller = Path(root, "app", "src/main/java/DemoController.java")
            controller.write_text(source, encoding="utf-8")
            Path(root, "app", "build.gradle.kts").write_text('implementation(project(":model"))', encoding="utf-8")
            Path(root, "model", "build.gradle.kts").parent.mkdir(parents=True)
            Path(root, "model", "build.gradle.kts").write_text("", encoding="utf-8")
            document = scan_java_document([controller])
            modules = gradle_modules(controller)
        self.assertEqual("application/json", document.endpoints[0].content_type)
        self.assertEqual({"app", "model"}, {item.name for item in modules})

    def test_renders_plugin_markdown_contract(self):
        endpoint = Endpoint("query", "查询", "POST", "/v1/query", [], Field("request", "Request"),
                            "ResponseBaseVo<Response>", "Demo.java:1")
        classes = {
            "Request": [Field("code", "String", "编码", True, "", "A001")],
            "Response": [Field("id", "Long", "主键")],
            "ResponseBaseVo": [Field("data", "T", "返回数据")],
        }
        document = scan_java_document_from_values([endpoint], classes)
        markdown = render_markdown(document, "http://localhost:8080")
        self.assertIn("# 查询", markdown)
        self.assertIn("### 请求地址", markdown)
        self.assertIn("### 入参字段说明", markdown)
        self.assertIn("| code     | **String**     | **是**", markdown)
        self.assertIn("### 出参字段说明", markdown)
        self.assertIn("curl -X POST", render_curl(document, "http://localhost:8080"))


def scan_java_document_from_values(endpoints, classes):
    from api_document_ir import ApiDocument
    return ApiDocument.from_legacy("java", "spring", endpoints, classes)


class KnownRegressionTests(unittest.TestCase):
    def test_fastapi_multiple_body_fields_are_combined_in_one_object(self):
        source = '''
            from fastapi import FastAPI, Body
            app = FastAPI()
            @app.post("/sum")
            def add(a: int = Body(), b: str = Body(alias="second")) -> int:
                return a
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "api.py").write_text(textwrap.dedent(source), encoding="utf-8")
            document = scan_python_document([Path(directory)])
        endpoint = document.endpoints[0]
        self.assertIsNotNone(endpoint.request_body)
        body = json.loads(render_postman(document, "")["item"][0]["request"]["body"]["raw"])
        self.assertEqual({"a": 1, "second": "HelloWorld"}, body)
        markdown = render_markdown(document, "")
        self.assertIn('"a": 1', markdown)
        self.assertIn('"second": "HelloWorld"', markdown)
        self.assertIn("| a", markdown)
        self.assertIn("| second", markdown)
        self.assertIn('"second": "HelloWorld"', render_curl(document, ""))

    def test_fastapi_body_embed_wraps_one_field_without_changing_plain_body(self):
        source = '''
            from fastapi import FastAPI, Body
            app = FastAPI()
            @app.post("/embedded")
            def embedded(q: str = Body(embed=True)) -> None: pass
            @app.post("/plain")
            def plain(q: str = Body()) -> None: pass
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "api.py").write_text(textwrap.dedent(source), encoding="utf-8")
            document = scan_python_document([Path(directory)])
        requests = {item["name"]: json.loads(item["request"]["body"]["raw"])
                    for item in render_postman(document, "")["item"]}
        self.assertEqual({"q": "HelloWorld"}, requests["embedded"])
        self.assertEqual("HelloWorld", requests["plain"])

    def test_fastapi_typed_dict_response_has_an_example(self):
        source = '''
            from fastapi import FastAPI
            app = FastAPI()
            @app.get("/stats", response_model=dict[str, int])
            def stats(): return {}
            @app.get("/generic", response_model=dict)
            def generic(): return {}
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "api.py").write_text(textwrap.dedent(source), encoding="utf-8")
            document = scan_python_document([Path(directory)])
        markdown = render_markdown(document, "")
        self.assertIn('"key": 1', markdown)
        self.assertIn('"key": "HelloWorld"', markdown)
        self.assertNotIn("此接口无任何出参", markdown)

    def test_fastapi_missing_return_type_is_unknown_without_empty_field_row(self):
        source = '''
            from fastapi import FastAPI
            app = FastAPI()
            @app.get("/unknown")
            def unknown(): return {"status": "ok"}
            @app.get("/none")
            def none() -> None: return None
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "api.py").write_text(textwrap.dedent(source), encoding="utf-8")
            document = scan_python_document([Path(directory)])
        markdown = render_markdown(document, "")
        unknown = markdown.split("# unknown", 1)[1]
        self.assertIn("未声明出参类型，无法生成示例", unknown)
        self.assertNotIn("### 出参字段说明", unknown)

    def test_fastapi_annotated_parameters_keep_header_cookie_and_form_locations(self):
        source = '''
            import typing as t
            from fastapi import FastAPI, Header, Cookie, Form
            app = FastAPI()
            @app.post("/items")
            def create(token: t.Annotated[str, Header(alias="X-Token")],
                       session: t.Annotated[str, Cookie()],
                       name: t.Annotated[str, Form()]): return None
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "api.py").write_text(textwrap.dedent(source), encoding="utf-8")
            document = scan_python_document([Path(directory)])
        endpoint = document.endpoints[0]
        self.assertEqual(["header", "cookie", "form"], [item.location for item in endpoint.parameters])
        self.assertEqual([True, True, True], [item.required for item in endpoint.parameters])
        self.assertEqual("application/x-www-form-urlencoded", endpoint.content_type)
        curl = render_curl(document, "https://example.test")
        self.assertIn("X-Token: HelloWorld", curl)
        self.assertIn("session=HelloWorld", curl)
        self.assertIn("--data-urlencode name=HelloWorld", curl)
        self.assertNotIn("?token=", curl)
        request = render_postman(document, "https://example.test")["item"][0]["request"]
        self.assertEqual("urlencoded", request["body"]["mode"])
        self.assertEqual(["name"], [item["key"] for item in request["body"]["urlencoded"]])

    def test_fastapi_typed_path_converter_is_filled_in_examples(self):
        source = '''
            from fastapi import FastAPI
            app = FastAPI()
            @app.get("/items/{item_id:int}")
            def item(item_id: int): return None
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "api.py").write_text(textwrap.dedent(source), encoding="utf-8")
            document = scan_python_document([Path(directory)])
        self.assertEqual("path", document.endpoints[0].parameters[0].location)
        curl = render_curl(document, "https://example.test")
        self.assertIn("/items/1", curl)
        self.assertNotIn("item_id=", curl)
        self.assertNotIn("{item_id:int}", render_markdown(document, ""))

    def test_fastapi_list_query_uses_repeated_query_key(self):
        source = '''
            from fastapi import FastAPI, Query
            app = FastAPI()
            @app.get("/search")
            def search(tags: list[str] = Query()): return None
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "api.py").write_text(textwrap.dedent(source), encoding="utf-8")
            document = scan_python_document([Path(directory)])
        curl = render_curl(document, "https://example.test")
        self.assertIn("/search?tags=HelloWorld", curl)
        self.assertNotIn("%7B%7D", curl)
        request = render_postman(document, "https://example.test")["item"][0]["request"]
        self.assertEqual(["tags"], [item["key"] for item in request["url"]["query"]])

    def test_fastapi_list_query_default_repeats_wire_key(self):
        source = '''
            from fastapi import FastAPI, Query
            app = FastAPI()
            @app.get("/search")
            def search(tags: list[str] = Query(["red", "blue"])): return None
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "api.py").write_text(textwrap.dedent(source), encoding="utf-8")
            document = scan_python_document([Path(directory)])
        self.assertIn("/search?tags=red&tags=blue", render_curl(document, "https://example.test"))
        query = render_postman(document, "https://example.test")["item"][0]["request"]["url"]["query"]
        self.assertEqual([("tags", "red"), ("tags", "blue")], [(item["key"], item["value"]) for item in query])

    def test_fastapi_literal_defaults_are_used_in_examples(self):
        source = '''
            from fastapi import FastAPI, Query
            app = FastAPI()
            def computed(): return 99
            @app.get("/search")
            def search(limit: int = 25, q: str = "books", page: int = 0,
                       enabled: bool = False, empty: str = "",
                       offset: int = Query(5), dynamic: int = computed()): return None
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "api.py").write_text(textwrap.dedent(source), encoding="utf-8")
            document = scan_python_document([Path(directory)])
        curl = render_curl(document, "https://example.test")
        self.assertIn("limit=25", curl)
        self.assertIn("q=books", curl)
        self.assertIn("page=0", curl)
        self.assertIn("enabled=false", curl)
        self.assertIn("empty=", curl)
        self.assertIn("offset=5", curl)
        self.assertIn("dynamic=1", curl)

    def test_fastapi_path_header_cookie_and_optional_query_use_correct_locations(self):
        source = '''
            from fastapi import FastAPI, Header, Cookie
            app = FastAPI()
            @app.get("/users/{user_id}")
            def user(user_id: int, x_token: str = Header(), session: str = Cookie(),
                     q: str | None = None):
                return None
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "api.py").write_text(textwrap.dedent(source), encoding="utf-8")
            document = scan_python_document([Path(directory)])
        self.assertEqual(["path", "header", "cookie", "query"],
                         [field.location for field in document.endpoints[0].parameters])
        curl = render_curl(document, "https://example.test")
        self.assertIn("/users/1", curl)
        self.assertIn("x-token: HelloWorld", curl)
        self.assertIn("session=HelloWorld", curl)
        self.assertIn("q=HelloWorld", curl)
        self.assertNotIn("q={}", curl)
        self.assertNotIn("--data-urlencode", curl)
        request = render_postman(document, "https://example.test")["item"][0]["request"]
        self.assertIn("/users/1", request["url"]["raw"])
        self.assertEqual(["q"], [item["key"] for item in request["url"]["query"]])
        self.assertIn({"key": "x-token", "value": "HelloWorld"}, request["header"])
        self.assertIn({"key": "Cookie", "value": "session=HelloWorld"}, request["header"])

    def test_unrelated_get_decorator_is_not_an_endpoint(self):
        source = '''
            from fastapi import FastAPI
            app = FastAPI()
            class Registry:
                def get(self, path):
                    return lambda function: function
            registry = Registry()
            @registry.get("/fake")
            def fake(): pass
            @app.get("/real")
            def real(): pass
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "api.py").write_text(textwrap.dedent(source), encoding="utf-8")
            document = scan_python_document([Path(directory)])
        self.assertEqual(["/real"], [endpoint.path for endpoint in document.endpoints])

    def test_fastapi_module_alias_and_header_settings(self):
        source = '''
            import fastapi as fa
            router = fa.APIRouter(prefix="/v1")
            @router.get("/status")
            def status(raw_token: str = fa.Header(convert_underscores=False)):
                return None
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "api.py").write_text(textwrap.dedent(source), encoding="utf-8")
            document = scan_python_document([Path(directory)])
        self.assertEqual("/v1/status", document.endpoints[0].path)
        self.assertEqual("raw_token", document.endpoints[0].parameters[0].wire_name)

    def test_fastapi_source_scan_skips_local_virtualenv(self):
        source = 'from fastapi import FastAPI\napp = FastAPI()\n@app.get("/route")\ndef route(): pass\n'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Path(root, "api.py").write_text(source, encoding="utf-8")
            Path(root, ".venv").mkdir()
            Path(root, ".venv", "dependency.py").write_text(
                source.replace("/route", "/dependency"), encoding="utf-8")
            document = scan_python_document([root])
        self.assertEqual(["/route"], [endpoint.path for endpoint in document.endpoints])

    def test_false_response_has_example(self):
        document = scan_java_document_from_values([
            Endpoint("flag", "flag", "GET", "/flag", [], None, "boolean", "Demo.java:1")], {})
        markdown = render_markdown(document, "")
        self.assertIn("### 出参示例\n```json\nfalse\n```", markdown)
        self.assertNotIn("此接口无任何出参", markdown)

    def test_query_values_are_encoded_and_post_query_is_in_url(self):
        document = scan_java_document_from_values([
            Endpoint("search", "search", "POST", "/search",
                     [Field("q", "String", example="a&b", location="query")], None,
                     "void", "Demo.java:1")], {})
        curl = render_curl(document, "https://example.test")
        self.assertIn("/search?q=a%26b", curl)
        self.assertNotIn("--data-urlencode", curl)
        request = render_postman(document, "https://example.test")["item"][0]["request"]
        self.assertEqual("a&b", request["url"]["query"][0]["value"])

    def test_java_post_request_param_remains_form_data(self):
        source = '''
            @RestController class DemoController {
                @PostMapping("/submit") void submit(@RequestParam String code) { }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "DemoController.java").write_text(source, encoding="utf-8")
            document = scan_java_document([Path(directory)])
        self.assertEqual("form", document.endpoints[0].parameters[0].location)
        self.assertIn("--data-urlencode", render_curl(document, ""))

    def test_java_path_and_header_annotation_names_are_used_on_wire(self):
        source = '''
            @RestController class DemoController {
                @GetMapping("/users/{user_id}") void user(
                    @PathVariable(name = "user_id") int userId,
                    @RequestHeader("X-Token") String token) { }
            }
        '''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "DemoController.java").write_text(source, encoding="utf-8")
            document = scan_java_document([Path(directory)])
        curl = render_curl(document, "https://example.test")
        self.assertIn("/users/0", curl)
        self.assertIn("X-Token: <token>", curl)
        self.assertNotIn("user_id=", curl)

    def test_markdown_table_escapes_pipe_in_field_text(self):
        document = scan_java_document_from_values([
            Endpoint("find", "find", "GET", "/find",
                     [Field("q", "String", "one|two", location="query")], None,
                     "String", "Demo.java:1")], {})
        self.assertIn("one\\|two", render_markdown(document, ""))


class RemainingBugTests(unittest.TestCase):
    def java(self, source):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "Demo.java").write_text(textwrap.dedent(source), encoding="utf-8")
            return scan_java_document([Path(directory)])

    def python(self, source):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "api.py").write_text(textwrap.dedent(source), encoding="utf-8")
            return scan_python_document([Path(directory)])

    def test_multiline_notes_are_each_shell_comments(self):
        document = self.python('''
            from fastapi import FastAPI
            app = FastAPI()
            @app.get("/ping")
            def ping() -> str:
                """Ping\\n    echo INJECTED"""
                return "ok"
        ''')
        curl = render_curl(document, "")
        self.assertIn("# echo INJECTED", curl)
        self.assertNotIn("\necho INJECTED\n", curl)

    def test_spring_mapping_arrays_expand_to_valid_endpoints(self):
        document = self.java('''
            @RestController @RequestMapping({"/v1", "/v2"}) class Demo {
                @GetMapping({"/a", "/b"}) void get() {}
                @RequestMapping(value="/both", method={RequestMethod.GET, RequestMethod.POST}) void both() {}
            }
        ''')
        self.assertEqual({("GET", f"/{prefix}/{route}") for prefix in ("v1", "v2")
                          for route in ("a", "b", "both")}
                         | {("POST", f"/{prefix}/both") for prefix in ("v1", "v2")},
                         {(item.method, item.path) for item in document.endpoints})
        self.assertNotIn("GET/POST", render_curl(document, ""))

    def test_spring_unrestricted_mapping_has_concrete_methods(self):
        document = self.java('@RestController class Demo { @RequestMapping("/any") void any() {} }')
        self.assertIn("GET", {item.method for item in document.endpoints})
        self.assertIn("POST", {item.method for item in document.endpoints})
        self.assertTrue(all("/" not in item.method for item in document.endpoints))

    def test_spring_composed_mapping_keeps_all_declared_methods(self):
        document = self.java('''
            @RequestMapping(method={RequestMethod.GET, RequestMethod.POST})
            @interface ReadWrite { String[] value() default {}; }
            @RestController class Demo { @ReadWrite("/items") void items() {} }
        ''')
        self.assertEqual({("GET", "/items"), ("POST", "/items")},
                         {(item.method, item.path) for item in document.endpoints})

    def test_spring_binding_required_defaults_and_examples(self):
        document = self.java('''
            @RestController class Demo {
                @PostMapping("/users/{id}") void create(@PathVariable int id,
                    @RequestHeader("X-Token") String token, @RequestBody String body,
                    @RequestParam(defaultValue="all") String scope,
                    @RequestParam(required=false) String optional) {}
            }
        ''')
        endpoint = document.endpoints[0]
        self.assertEqual([(True, True, False, False), "all"],
                         [tuple(item.required for item in endpoint.parameters), endpoint.parameters[2].example])
        self.assertTrue(endpoint.request_body.required)
        self.assertIn("scope=all", render_curl(document, ""))

    def test_spring_empty_default_is_optional_and_kept_empty(self):
        document = self.java('''
            @RestController class Demo {
                @GetMapping("/search") void search(@RequestParam(defaultValue="") String q) {}
            }
        ''')
        self.assertFalse(document.endpoints[0].parameters[0].required)
        self.assertIn("?q=", render_curl(document, ""))
        self.assertNotIn("<q>", render_curl(document, ""))

    def test_fastapi_upload_is_file_in_postman_and_curl(self):
        document = self.python('''
            from fastapi import FastAPI, UploadFile, File, Form
            app = FastAPI()
            @app.post("/upload")
            def upload(file: UploadFile = File(), title: str = Form()): pass
        ''')
        form = render_postman(document, "")["item"][0]["request"]["body"]["formdata"]
        self.assertEqual("file", form[0]["type"])
        self.assertEqual("text", form[1]["type"])
        self.assertIn("file=@", render_curl(document, ""))

    def test_java_multipart_file_is_file(self):
        document = self.java('''
            @RestController class Demo {
                @PostMapping("/upload") void upload(@RequestPart MultipartFile file, @RequestPart String note) {}
            }
        ''')
        self.assertEqual("file", document.endpoints[0].parameters[0].location)
        self.assertEqual("file", render_postman(document, "")["item"][0]["request"]["body"]["formdata"][0]["type"])

    def test_java_multipart_file_array_is_file(self):
        document = self.java('''
            @RestController class Demo {
                @PostMapping("/upload") void upload(@RequestPart MultipartFile[] files) {}
            }
        ''')
        self.assertEqual("file", document.endpoints[0].parameters[0].location)
        form = render_postman(document, "")["item"][0]["request"]["body"]["formdata"]
        self.assertEqual("file", form[0]["type"])
        self.assertIn("files=@", render_curl(document, ""))

    def test_java_arrays_render_as_arrays(self):
        document = self.java('''
            class User { String name; }
            @RestController class Demo {
                @PostMapping("/ids") void ids(@RequestBody int[] ids) {}
                @GetMapping("/users") User[] users() { return null; }
            }
        ''')
        postman = render_postman(document, "")
        self.assertEqual([0], json.loads(next(item for item in postman["item"] if item["name"] == "ids")["request"]["body"]["raw"]))
        self.assertIn('"name"', render_markdown(document, ""))
        self.assertIn('[\n  {', render_markdown(document, ""))

    def test_response_entity_unwraps_body_schema(self):
        document = self.java('''
            class User { String name; }
            @RestController class Demo {
                @GetMapping("/user") ResponseEntity<User> user() { return null; }
            }
        ''')
        markdown = render_markdown(document, "")
        self.assertIn('"name"', markdown)
        self.assertIn("| name", markdown)
        self.assertNotIn("此接口无任何出参", markdown)

    def test_response_entity_list_has_nested_field_rows(self):
        document = self.java('''
            class User { String name; }
            @RestController class Demo {
                @GetMapping("/users") ResponseEntity<List<User>> users() { return null; }
            }
        ''')
        markdown = render_markdown(document, "")
        self.assertIn('"name"', markdown)
        self.assertIn("| name", markdown)

    def test_typed_fastapi_instances_and_api_route_methods(self):
        document = self.python('''
            from fastapi import FastAPI, APIRouter
            app: FastAPI = FastAPI()
            router: APIRouter = APIRouter(prefix="/v1")
            @app.api_route("/health", methods=["GET", "HEAD"])
            def health(): pass
            @router.get("/items")
            def items(): pass
        ''')
        self.assertEqual({("GET", "/health"), ("HEAD", "/health"), ("GET", "/v1/items")},
                         {(item.method, item.path) for item in document.endpoints})

    def test_overload_selector_requires_disambiguation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Path(root, "Demo.java").write_text('''
                @RestController class Demo {
                    @GetMapping("/x") void find() {}
                    @PostMapping("/x") void find(@RequestBody String body) {}
                }
            ''', encoding="utf-8")
            script = str(Path(__file__).with_name("generate_api_docs.py"))
            args = [sys.executable, script, "--source", str(root), "--output-file", str(root / "one.md")]
            ambiguous = subprocess.run(args + ["--endpoint", "find"], capture_output=True, text=True)
            self.assertNotEqual(0, ambiguous.returncode)
            self.assertIn("ambiguous", ambiguous.stderr.lower())
            selected = subprocess.run(args + ["--endpoint", "find@POST:/x"], capture_output=True, text=True)
            self.assertEqual(0, selected.returncode, selected.stderr)
            self.assertIn("Generated 1 endpoint", selected.stdout)

    def test_multipart_alias_repeated_files_and_literal_text(self):
        document = self.java('''
            @RestController class Demo {
                @PostMapping("/upload") void upload(@RequestPart("file-data") MultipartFile[] files,
                    @RequestPart String note) {}
            }
        ''')
        fields = document.endpoints[0].parameters
        self.assertEqual("file-data", fields[0].wire_name)
        form = render_postman(document, "")["item"][0]["request"]["body"]["formdata"]
        self.assertEqual("file-data", form[0]["key"])
        curl = render_curl(document, "")
        self.assertIn("file-data=@/path/to/file", curl)
        self.assertIn("--form-string", curl)
        self.assertIn("note=<note>", curl)

    def test_java_mapping_constant_and_composed_annotation_namespaces(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Routes.java").write_text('class Routes { static final String ITEMS = "/items"; }', encoding="utf-8")
            (root / "A.java").write_text('package a; @GetMapping @interface Fetch { String value() default ""; }', encoding="utf-8")
            (root / "B.java").write_text('package b; @PostMapping @interface Fetch { String value() default ""; }', encoding="utf-8")
            (root / "Demo.java").write_text('import a.Fetch; @RestController class Demo { @GetMapping(Routes.ITEMS) void items() {} @Fetch("/a") void a() {} }', encoding="utf-8")
            document = scan_java_document([root])
        self.assertIn(("GET", "/items"), {(e.method, e.path) for e in document.endpoints})
        self.assertIn(("GET", "/a"), {(e.method, e.path) for e in document.endpoints})

    def test_java_omits_nonserializable_and_framework_parameters(self):
        document = self.java('''
            class Payload { static final long serialVersionUID = 1L; transient String cache;
                @JsonIgnore String secret; String name; }
            @RestController class Demo {
                @PostMapping("/users/{id}") void save(@PathVariable int id, HttpServletRequest request,
                    @CookieValue("sid") String session, @RequestBody Payload payload) {}
            }
        ''')
        endpoint = document.endpoints[0]
        self.assertEqual([("id", "path"), ("session", "cookie")],
                         [(p.name, p.location) for p in endpoint.parameters])
        self.assertEqual("sid", endpoint.parameters[1].wire_name)
        self.assertEqual({"name"}, {f.name for f in document.schemas[endpoint.request_body.schema_id].fields})

    def test_java_optional_and_schema_metadata(self):
        document = self.java('''
            class Payload { @Schema(description="User ID", example="42", requiredMode=Schema.RequiredMode.REQUIRED)
                String id; }
            @RestController class Demo { @PostMapping("/save") void save(
                @RequestParam Optional<String> q, @RequestBody Payload payload) {} }
        ''')
        self.assertFalse(document.endpoints[0].parameters[0].required)
        field = document.schemas[document.endpoints[0].request_body.schema_id].fields[0]
        self.assertEqual(("User ID", "42", True), (field.description, field.example, field.required))

    def test_java_path_and_header_only_have_no_form_body(self):
        document = self.java('''
            @RestController class Demo { @PostMapping("/items/{id}") void get(
                @PathVariable int id, @RequestHeader String token) {} }
        ''')
        self.assertEqual("", document.endpoints[0].content_type)

    def test_enum_collections_and_transformed_json_value(self):
        document = self.java('''
            enum State { READY(1); private int code; State(int code) { this.code = code + 10; }
                @JsonValue int getCode() { return code; } }
            class Payload { List<State> states; }
            @RestController class Demo { @PostMapping("/save") void save(@RequestBody Payload p) {} }
        ''')
        option = next(s.enum_options[0] for s in document.schemas.values() if s.name == "State")
        self.assertFalse(option.value_resolved)
        body = json.loads(render_postman(document, "")["item"][0]["request"]["body"]["raw"])
        self.assertIsInstance(body["states"], list)

    def test_unresolved_response_is_not_described_as_empty(self):
        document = self.java('@RestController class Demo { @GetMapping("/x") MissingDto x() { return null; } }')
        self.assertNotIn("此接口无任何出参", render_markdown(document, ""))

    def test_nested_response_schema_keeps_qualified_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "A.java").write_text('package a; public class User { public String fromA; }', encoding="utf-8")
            (root / "B.java").write_text('package b; public class User { public String fromB; }', encoding="utf-8")
            (root / "Demo.java").write_text('import a.User; @RestController class Demo { @GetMapping("/users") ResponseEntity<List<User>> users() { return null; } }', encoding="utf-8")
            document = scan_java_document([root])
        markdown = render_markdown(document, "")
        self.assertIn('"fromA"', markdown)
        self.assertNotIn('"fromB"', markdown)

    def test_python_imported_app_decorators_constants_and_deduplicated_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text('from fastapi import FastAPI\napp = FastAPI()\nfrom routes import routes\n', encoding="utf-8")
            route = root / "routes.py"
            route.write_text('from app import app\nMETHODS = ["POST"]\n@app.api_route("/submit", methods=METHODS)\ndef routes(): pass\n', encoding="utf-8")
            document = scan_python_document([root, route])
        self.assertEqual([("POST", "/submit")], [(e.method, e.path) for e in document.endpoints])

    def test_python_stacked_routes_dependency_parameters_and_alias_markers(self):
        document = self.python('''
            from fastapi import FastAPI, Depends, Header as H, Body as B
            app = FastAPI()
            def auth(x_token: str = H()): pass
            @app.get("/read")
            @app.post("/write")
            def item(user = Depends(auth), payload: str = B()): pass
        ''')
        self.assertEqual({("GET", "/read"), ("POST", "/write")},
                         {(e.method, e.path) for e in document.endpoints})
        for endpoint in document.endpoints:
            self.assertIn(("x_token", "header"), [(p.name, p.location) for p in endpoint.parameters])
            self.assertIsNotNone(endpoint.request_body)

    def test_python_injected_request_and_required_path(self):
        document = self.python('''
            from fastapi import FastAPI, Request
            app = FastAPI()
            @app.get("/items/{item_id}")
            def item(req: Request, item_id: int | None = None): pass
        ''')
        self.assertEqual([("item_id", "path", True)],
                         [(p.name, p.location, p.required) for p in document.endpoints[0].parameters])

    def test_curl_without_base_url_has_a_host(self):
        document = self.python('from fastapi import FastAPI\napp = FastAPI()\n@app.get("/ping")\ndef ping(): pass')
        self.assertIn("http://localhost:8000/ping", render_curl(document, ""))

    def test_java_json_control_characters_are_escaped(self):
        source = '@RestController class Demo { @GetMapping("/x") void x(@Schema(example="a' + chr(92) + 'b") String value) {} }'
        document = self.java(source)
        self.assertEqual("a\b", document.endpoints[0].parameters[0].example)

    def test_java_composed_mapping_uses_imported_definition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for package, method in (("a", "GetMapping"), ("b", "PostMapping")):
                folder = root / package
                folder.mkdir()
                (folder / "Fetch.java").write_text(
                    f'package {package}; @{method} public @interface Fetch {{ String value() default ""; }}',
                    encoding="utf-8")
            (root / "Demo.java").write_text('import a.Fetch; @RestController class Demo { @Fetch("/read") void read() {} }', encoding="utf-8")
            document = scan_java_document([root])
        self.assertEqual([("GET", "/read")], [(e.method, e.path) for e in document.endpoints])

    def test_java_unqualified_constant_and_optional_dto(self):
        document = self.java('''
            class User { String name; }
            @RestController class Demo {
                static final String BASE = "/api";
                @GetMapping(BASE + "/user") Optional<User> user() { return null; }
            }
        ''')
        self.assertEqual("/api/user", document.endpoints[0].path)
        self.assertIn('"name"', render_markdown(document, ""))

    def test_java_json_ignore_false_is_serialized(self):
        document = self.java('''
            class User { @JsonIgnore(false) String visible; @JsonIgnore String hidden; }
            @RestController class Demo { @PostMapping("/x") void x(@RequestBody User user) {} }
        ''')
        fields = document.schemas[document.endpoints[0].request_body.schema_id].fields
        self.assertEqual(["visible"], [field.name for field in fields])

    def test_jar_fallback_reads_final_array_and_skips_static_transient(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "User.java").write_text('public class User { private final String name = "x"; private int[] ids; private static long serialVersionUID; private transient String cache; }', encoding="utf-8")
            subprocess.run(["javac", "User.java"], cwd=root, check=True, capture_output=True)
            subprocess.run(["jar", "cf", "user.jar", "User.class"], cwd=root, check=True, capture_output=True)
            classes, _ = parse_class_from_jar([root / "user.jar"], "User")
        self.assertEqual({"name", "ids"}, {field.name for field in classes["User"]})

    def test_python_api_route_default_and_unknown_methods(self):
        diagnostics = io.StringIO()
        with contextlib.redirect_stderr(diagnostics):
            document = self.python('''
            from fastapi import FastAPI
            app = FastAPI()
            METHODS = unknown_methods()
            @app.api_route("/default")
            def default(): pass
            @app.api_route("/unknown", methods=METHODS)
            def unknown(): pass
        ''')
        self.assertEqual([("GET", "/default")], [(e.method, e.path) for e in document.endpoints])
        self.assertIn("unresolved FastAPI mapping", diagnostics.getvalue())

    def test_java_route_constant_respects_import_with_same_name_elsewhere(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for package, route in (("a", "/a"), ("b", "/b")):
                folder = root / package
                folder.mkdir()
                (folder / "Routes.java").write_text(
                    f'package {package}; public class Routes {{ public static final String ITEMS = "{route}"; }}',
                    encoding="utf-8")
            (root / "Demo.java").write_text('import a.Routes; @RestController class Demo { @GetMapping(Routes.ITEMS) void items() {} }', encoding="utf-8")
            document = scan_java_document([root])
        self.assertEqual("/a", document.endpoints[0].path)

    def test_resolved_duplicate_schema_does_not_warn_as_unresolved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "A.java").write_text('package a; public class User { String a; }', encoding="utf-8")
            (root / "B.java").write_text('package b; public class User { String b; }', encoding="utf-8")
            (root / "Demo.java").write_text('import a.User; @RestController class Demo { @GetMapping("/x") User x() { return null; } }', encoding="utf-8")
            document = scan_java_document([root])
        self.assertNotIn("User", unresolved_types(document.endpoints, document.classes(), document.schemas))

    def test_python_imported_route_constants(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "paths.py").write_text('PREFIX = "/v1"\nPATH: str = "/submit"\nMETHODS = ["POST"]\n', encoding="utf-8")
            (root / "api.py").write_text('from fastapi import APIRouter\nfrom paths import PREFIX, PATH, METHODS\nrouter = APIRouter(prefix=PREFIX)\n@router.api_route(PATH, methods=METHODS)\ndef submit(): pass\n', encoding="utf-8")
            document = scan_python_document([root])
        self.assertEqual([("POST", "/v1/submit")], [(e.method, e.path) for e in document.endpoints])

    def test_java_json_property_access_and_class_ignores_follow_direction(self):
        document = self.java('''
            @JsonIgnoreProperties({"secret"}) class User {
                @JsonProperty(access=JsonProperty.Access.READ_ONLY) String id;
                @JsonProperty(access=JsonProperty.Access.WRITE_ONLY) String password;
                String secret; String name;
            }
            @RestController class Demo { @PostMapping("/user") User save(@RequestBody User user) { return null; } }
        ''')
        request = render_postman(document, "")["item"][0]["request"]
        body = json.loads(request["body"]["raw"])
        self.assertEqual({"password", "name"}, set(body))
        markdown = render_markdown(document, "")
        response = markdown.split("## 出参", 1)[1]
        self.assertIn('"id"', response)
        self.assertNotIn('"password"', response)
        self.assertNotIn('"secret"', markdown)

    def test_json_ignore_properties_allow_getters_and_setters(self):
        document = self.java('''
            @JsonIgnoreProperties(value={"serverId"}, allowGetters=true)
            class View { String serverId; String name; }
            @JsonIgnoreProperties(value={"clientSecret"}, allowSetters=true)
            class Input { String clientSecret; String name; }
            @RestController class Demo {
                @PostMapping("/view") View view(@RequestBody View value) { return null; }
                @PostMapping("/input") Input input(@RequestBody Input value) { return null; }
            }
        ''')
        postman = {item["request"]["url"]: json.loads(item["request"]["body"]["raw"])
                   for item in render_postman(document, "")["item"]}
        self.assertEqual({"name"}, set(postman["/view"]))
        self.assertEqual({"clientSecret", "name"}, set(postman["/input"]))
        markdown = render_markdown(document, "")
        view = markdown.split("# view", 1)[1].split("# input", 1)[0] if "# view" in markdown else markdown
        self.assertIn('"serverId"', view)
        self.assertNotIn('"clientSecret"', markdown.split("# input", 1)[1].split("## 出参", 1)[1])

    def test_java_feign_constant_and_class_consumes(self):
        document = self.java('''
            class Routes { static final String ROOT = "/remote"; }
            @FeignClient(path=Routes.ROOT) interface Remote { @GetMapping("/x") String x(); }
            @RestController @RequestMapping(consumes="application/json") class Demo {
                @PostMapping("/save") void save(@RequestParam String code) {}
            }
        ''')
        self.assertIn("/remote/x", [item.path for item in document.endpoints])
        self.assertEqual("application/json", next(item.content_type for item in document.endpoints if item.name == "save"))

    def test_nested_enum_response_has_table(self):
        document = self.java('''
            enum State { READY; }
            @RestController class Demo { @GetMapping("/states") ResponseEntity<List<State>> states() { return null; } }
        ''')
        markdown = render_markdown(document, "")
        self.assertIn('"READY"', markdown)
        self.assertIn("### 出参 return", markdown)
        self.assertIn("| READY | READY |", markdown)

    def test_known_empty_response_is_rendered(self):
        document = self.java('class Empty {} @RestController class Demo { @GetMapping("/x") Empty x() { return null; } }')
        markdown = render_markdown(document, "")
        self.assertIn("### 出参示例\n```json\n{}", markdown)
        self.assertNotIn("未解析", markdown)

    def test_python_package_init_router_and_assignment_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "pkg"
            package.mkdir()
            (package / "__init__.py").write_text('from fastapi import APIRouter\nrouter = APIRouter(prefix="/pkg")\nPATH: str="/old"\nPATH="/new"\n@router.get(PATH)\ndef item(): pass\n', encoding="utf-8")
            (root / "app.py").write_text('from fastapi import FastAPI\nfrom pkg import router\napp=FastAPI()\napp.include_router(router,prefix="/v1")\n', encoding="utf-8")
            document = scan_python_document([root])
        self.assertEqual(["/v1/pkg/new"], [item.path for item in document.endpoints])

    def test_python_package_directory_as_source_root(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "pkg"
            package.mkdir()
            (package / "__init__.py").write_text('from fastapi import APIRouter\nrouter = APIRouter(prefix="/pkg")\n@router.get("/x")\ndef x(): pass\n', encoding="utf-8")
            document = scan_python_document([package])
            self.assertEqual("pkg", module_name(package / "__init__.py", [package]))
        self.assertEqual(["/pkg/x"], [item.path for item in document.endpoints])

    def test_fastapi_decorator_router_include_and_app_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "routes.py").write_text('''from fastapi import APIRouter, Depends, Header
def router_auth(router_token: str = Header()): pass
def route_auth(route_token: str = Header()): pass
router = APIRouter(prefix="/r", dependencies=[Depends(router_auth)])
@router.get("/x", dependencies=[Depends(route_auth)])
def x(): pass
''', encoding="utf-8")
            (root / "app.py").write_text('''from fastapi import FastAPI, Depends, Header
from routes import router
def app_auth(app_token: str = Header()): pass
def include_auth(include_token: str = Header()): pass
app = FastAPI(dependencies=[Depends(app_auth)])
app.include_router(router, dependencies=[Depends(include_auth)])
''', encoding="utf-8")
            document = scan_python_document([root])
        self.assertEqual("/r/x", document.endpoints[0].path)
        self.assertEqual({"app_token", "include_token", "router_token", "route_token"},
                         {field.name for field in document.endpoints[0].parameters})

    def test_fastapi_include_dependencies_stay_with_their_mount(self):
        document = self.python('''
            from fastapi import FastAPI, APIRouter, Depends, Header
            app = FastAPI()
            router = APIRouter()
            def left(x_left: str = Header()): pass
            def right(x_right: str = Header()): pass
            @router.get("/x")
            def item(): pass
            app.include_router(router, prefix="/left", dependencies=[Depends(left)])
            app.include_router(router, prefix="/right", dependencies=[Depends(right)])
        ''')
        fields = {endpoint.path: {field.name for field in endpoint.parameters}
                  for endpoint in document.endpoints}
        self.assertEqual({"/left/x": {"x_left"}, "/right/x": {"x_right"}}, fields)

    def test_fastapi_named_dependency_list(self):
        document = self.python('''
            from fastapi import FastAPI, Depends, Header
            app = FastAPI()
            def auth(x_token: str = Header()): pass
            AUTH = [Depends(auth)]
            @app.get("/x", dependencies=AUTH)
            def x(): pass
        ''')
        self.assertEqual([("x_token", "header")],
                         [(field.name, field.location) for field in document.endpoints[0].parameters])

    def test_fastapi_imported_dependency_list_keeps_source_bindings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "deps.py").write_text('from fastapi import Depends, Header\ndef auth(x_token: str=Header()): pass\nAUTH=[Depends(auth)]\n', encoding="utf-8")
            (root / "app.py").write_text('from fastapi import FastAPI\nfrom deps import AUTH\napp=FastAPI()\n@app.get("/x", dependencies=AUTH)\ndef x(): pass\n', encoding="utf-8")
            document = scan_python_document([root])
        self.assertEqual([("x_token", "header")],
                         [(field.name, field.location) for field in document.endpoints[0].parameters])

    def test_gradle_named_project_path_discovers_module(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "settings.gradle").write_text("include ':service', ':model'", encoding="utf-8")
            service, model = root / "service", root / "model"
            service.mkdir(); model.mkdir()
            (service / "build.gradle").write_text("implementation project(path: ':model')", encoding="utf-8")
            (model / "build.gradle").write_text("plugins {}", encoding="utf-8")
            controller = service / "Controller.java"
            controller.write_text("class Controller {}", encoding="utf-8")
            self.assertEqual({service, model}, set(gradle_modules(controller)))

    def test_jar_fallback_uses_imported_qualified_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jars = []
            for package in ("a", "b"):
                folder = root / package
                folder.mkdir()
                (folder / "User.java").write_text(f'package {package}; public class User {{ public String from{package.upper()}; }}', encoding="utf-8")
                subprocess.run(["javac", str(folder / "User.java")], check=True, capture_output=True)
                jar = root / f"{package}.jar"
                subprocess.run(["jar", "cf", str(jar), f"{package}/User.class"], cwd=root, check=True, capture_output=True)
                jars.append(jar)
            (root / "Demo.java").write_text('import b.User; @RestController class Demo { @GetMapping("/x") User x() { return null; } }', encoding="utf-8")
            output = root / "out.md"
            run = subprocess.run([sys.executable, str(Path(__file__).with_name("generate_api_docs.py")),
                                  "--source", str(root / "Demo.java"), "--classpath", str(jars[0]),
                                  "--classpath", str(jars[1]), "--output-file", str(output)],
                                 capture_output=True, text=True)
            self.assertEqual(0, run.returncode, run.stderr)
            markdown = output.read_text(encoding="utf-8")
            self.assertIn("fromB", markdown)
            self.assertNotIn("fromA", markdown)

    def test_jar_fallback_refuses_ambiguous_unqualified_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jars = []
            for package in ("a", "b"):
                folder = root / package
                folder.mkdir()
                (folder / "User.java").write_text(f'package {package}; public class User {{ public String field; }}', encoding="utf-8")
                subprocess.run(["javac", str(folder / "User.java")], check=True, capture_output=True)
                jar = root / f"{package}.jar"
                subprocess.run(["jar", "cf", str(jar), f"{package}/User.class"], cwd=root, check=True, capture_output=True)
                jars.append(jar)
            diagnostics = io.StringIO()
            with contextlib.redirect_stderr(diagnostics):
                parsed, _ = parse_class_from_jar(jars, "User")
            self.assertEqual({}, parsed)
            self.assertIn("ambiguous JAR DTO type", diagnostics.getvalue())

    def test_explicit_missing_java_type_never_uses_another_package(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "B.java").write_text('package b; public class User { public String fromB; }', encoding="utf-8")
            (root / "Demo.java").write_text('import a.User; @RestController class Demo { @GetMapping("/x") User x() { return null; } }', encoding="utf-8")
            document = scan_java_document([root])
        markdown = render_markdown(document, "")
        self.assertNotIn("fromB", markdown)
        self.assertIn("未解析", markdown)
        self.assertIn("a.User", unresolved_types(document.endpoints, document.classes(), document.schemas))

    def test_unresolved_nested_dto_does_not_generate_empty_json(self):
        document = self.java('''
            import java.util.List;
            @RestController class Demo {
                @PostMapping("/x") List<MissingDto> x(@RequestBody List<MissingDto> values) { return null; }
            }
        ''')
        markdown = render_markdown(document, "")
        self.assertNotIn("[\n  {}\n]", markdown)
        self.assertIn("请求体类型 List<MissingDto> 未解析", markdown)
        self.assertIn("出参类型 List<MissingDto> 未解析", markdown)
        self.assertNotIn("body", render_postman(document, "")["item"][0]["request"])
        self.assertNotIn("--data", render_curl(document, ""))

    def test_raw_list_request_does_not_recurse_forever(self):
        document = self.java('@RestController class Demo { @PostMapping("/x") void x(@RequestBody java.util.List values) {} }')
        self.assertEqual([], json.loads(render_postman(document, "")["item"][0]["request"]["body"]["raw"]))

    def test_xml_request_does_not_receive_json_payload(self):
        document = self.java('''
            class User { String name; }
            @RestController class Demo {
                @PostMapping(value="/x", consumes="application/xml") void x(@RequestBody User user) {}
            }
        ''')
        self.assertIn("非 JSON 请求体", render_markdown(document, ""))
        self.assertNotIn("body", render_postman(document, "")["item"][0]["request"])
        self.assertNotIn("--data", render_curl(document, ""))

    def test_jar_fallback_reads_package_private_fields_and_inheritance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Base.java").write_text('package a; public class Base { String baseName; }', encoding="utf-8")
            (root / "User.java").write_text('package a; public class User extends Base { String childName; }', encoding="utf-8")
            subprocess.run(["javac", "-d", str(root), str(root / "Base.java"), str(root / "User.java")], check=True, capture_output=True)
            jar = root / "models.jar"
            subprocess.run(["jar", "cf", str(jar), "a/Base.class", "a/User.class"], cwd=root, check=True, capture_output=True)
            (root / "Demo.java").write_text('import a.User; @RestController class Demo { @GetMapping("/x") User x() {return null;} }', encoding="utf-8")
            output = root / "out.md"
            run = subprocess.run([sys.executable, str(Path(__file__).with_name("generate_api_docs.py")),
                                  "--source", str(root / "Demo.java"), "--classpath", str(jar),
                                  "--output-file", str(output)], capture_output=True, text=True)
            self.assertEqual(0, run.returncode, run.stderr)
            markdown = output.read_text(encoding="utf-8")
        self.assertIn('"baseName"', markdown)
        self.assertIn('"childName"', markdown)

    def test_python_route_constant_uses_value_at_definition(self):
        document = self.python('''
            from fastapi import FastAPI
            app = FastAPI()
            PATH = "/old"
            @app.get(PATH)
            def x(): pass
            PATH = "/new"
        ''')
        self.assertEqual(["/old"], [endpoint.path for endpoint in document.endpoints])

    def test_python_router_and_include_prefixes_use_values_at_call(self):
        document = self.python('''
            from fastapi import FastAPI, APIRouter
            app = FastAPI()
            PREFIX = "/old"
            router = APIRouter(prefix=PREFIX)
            PREFIX = "/new"
            MOUNT = "/v1"
            app.include_router(router, prefix=MOUNT)
            MOUNT = "/v2"
            @router.get("/x")
            def x(): pass
        ''')
        self.assertEqual(["/v1/old/x"], [endpoint.path for endpoint in document.endpoints])

    def test_python_route_constant_follows_imports_in_defining_module(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "base.py").write_text('ROOT="/v1"\n', encoding="utf-8")
            (root / "paths.py").write_text('from base import ROOT\nAPI=ROOT + "/items"\n', encoding="utf-8")
            (root / "app.py").write_text('from fastapi import FastAPI\nfrom paths import API\napp=FastAPI()\n@app.get(API)\ndef x(): pass\n', encoding="utf-8")
            document = scan_python_document([root])
        self.assertEqual(["/v1/items"], [endpoint.path for endpoint in document.endpoints])

    def test_java_getter_json_annotations_affect_matching_dto_field(self):
        document = self.java('''
            class User {
                String secret; String name;
                @JsonIgnore String getSecret() { return secret; }
                @JsonProperty("wireName") String getName() { return name; }
            }
            @RestController class Demo { @PostMapping("/x") User x(@RequestBody User user) { return null; } }
        ''')
        body = json.loads(render_postman(document, "")["item"][0]["request"]["body"]["raw"])
        self.assertEqual({"wireName"}, set(body))
        markdown = render_markdown(document, "")
        self.assertIn('"wireName"', markdown)
        self.assertNotIn('"secret"', markdown)

    def test_java_class_ignore_applies_to_inherited_fields(self):
        document = self.java('''
            class Base { String secret; String name; }
            @JsonIgnoreProperties({"secret"}) class Child extends Base { String extra; }
            @RestController class Demo { @PostMapping("/x") Child x(@RequestBody Child value) { return null; } }
        ''')
        body = json.loads(render_postman(document, "")["item"][0]["request"]["body"]["raw"])
        self.assertEqual({"name", "extra"}, set(body))
        self.assertNotIn('"secret"', render_markdown(document, ""))

    def test_java_inherited_ignore_allows_getters_only_in_response(self):
        document = self.java('''
            class Base { String serverId; }
            @JsonIgnoreProperties(value={"serverId"}, allowGetters=true) class Child extends Base { String name; }
            @RestController class Demo { @PostMapping("/x") Child x(@RequestBody Child value) { return null; } }
        ''')
        body = json.loads(render_postman(document, "")["item"][0]["request"]["body"]["raw"])
        self.assertEqual({"name"}, set(body))
        self.assertIn('"serverId"', render_markdown(document, "").split("## 出参", 1)[1])

    def test_jar_generic_fields_resolve_nested_dto(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Child.java").write_text('package a; public class Child { public String code; }', encoding="utf-8")
            (root / "User.java").write_text('package a; public class User { public java.util.List<Child> children; public java.util.Map<String,Child> byCode; }', encoding="utf-8")
            subprocess.run(["javac", "-d", str(root), str(root / "Child.java"), str(root / "User.java")], check=True, capture_output=True)
            jar = root / "models.jar"
            subprocess.run(["jar", "cf", str(jar), "a/Child.class", "a/User.class"], cwd=root, check=True, capture_output=True)
            (root / "Demo.java").write_text('import a.User; @RestController class Demo { @GetMapping("/x") User x() {return null;} }', encoding="utf-8")
            output = root / "out.md"
            run = subprocess.run([sys.executable, str(Path(__file__).with_name("generate_api_docs.py")),
                                  "--source", str(root / "Demo.java"), "--classpath", str(jar),
                                  "--output-file", str(output)], capture_output=True, text=True)
            self.assertEqual(0, run.returncode, run.stderr)
            markdown = output.read_text(encoding="utf-8")
        self.assertIn('"children": [', markdown)
        self.assertIn('"byCode": {', markdown)
        self.assertEqual(2, markdown.count('"code":'))
        self.assertNotIn("未解析", markdown)

    def test_fastapi_keyword_include_router_keeps_mount_prefix(self):
        document = self.python('''
            from fastapi import FastAPI, APIRouter
            app = FastAPI()
            router = APIRouter(prefix="/r")
            app.include_router(router=router, prefix="/v1")
            @router.get("/x")
            def x(): pass
        ''')
        self.assertEqual(["/v1/r/x"], [endpoint.path for endpoint in document.endpoints])

    def test_fastapi_module_attribute_router_and_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "pkg"
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "routes.py").write_text('from fastapi import APIRouter\nrouter=APIRouter(prefix="/r")\n@router.get("/x")\ndef x(): pass\n', encoding="utf-8")
            (package / "deps.py").write_text('from fastapi import Header\ndef auth(x_token: str=Header()): pass\n', encoding="utf-8")
            (root / "app.py").write_text('from fastapi import FastAPI, Depends\nimport pkg.routes\nimport pkg.deps\napp=FastAPI()\napp.include_router(pkg.routes.router,prefix="/v1",dependencies=[Depends(pkg.deps.auth)])\n', encoding="utf-8")
            document = scan_python_document([root])
        self.assertEqual(["/v1/r/x"], [endpoint.path for endpoint in document.endpoints])
        self.assertEqual([("x_token", "header")],
                         [(field.name, field.location) for field in document.endpoints[0].parameters])

    def test_missing_java_parent_does_not_look_like_complete_schema(self):
        document = self.java('''
            class Child extends MissingBase { String name; }
            @RestController class Demo { @PostMapping("/x") Child x(@RequestBody Child value) {return null;} }
        ''')
        markdown = render_markdown(document, "")
        self.assertIn("请求体类型 Child 未解析", markdown)
        self.assertIn("出参类型 Child 未解析", markdown)
        self.assertNotIn('"name":', markdown)
        self.assertIn("MissingBase", unresolved_types(document.endpoints, document.classes(), document.schemas))

    def test_generic_parent_with_concrete_argument_remains_resolved(self):
        document = self.java('''
            class Base<T> { T value; }
            class Child<T> extends Base<T> { }
            class Payload { String code; }
            @RestController class Demo { @GetMapping("/x") Child<Payload> x() {return null;} }
        ''')
        markdown = render_markdown(document, "")
        self.assertIn('"value": {', markdown)
        self.assertIn('"code":', markdown)
        self.assertNotIn("未解析", markdown)

    def test_jar_generic_parent_loads_concrete_argument_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Base.java").write_text('package a; public class Base<T> { public T value; }', encoding="utf-8")
            (root / "Payload.java").write_text('package a; public class Payload { public String code; }', encoding="utf-8")
            (root / "Child.java").write_text('package a; public class Child extends Base<Payload> { }', encoding="utf-8")
            subprocess.run(["javac", "-d", str(root), str(root / "Base.java"), str(root / "Payload.java"), str(root / "Child.java")], check=True, capture_output=True)
            jar = root / "models.jar"
            subprocess.run(["jar", "cf", str(jar), "a/Base.class", "a/Payload.class", "a/Child.class"], cwd=root, check=True, capture_output=True)
            (root / "Demo.java").write_text('import a.Child; @RestController class Demo { @GetMapping("/x") Child x() {return null;} }', encoding="utf-8")
            output = root / "out.md"
            run = subprocess.run([sys.executable, str(Path(__file__).with_name("generate_api_docs.py")),
                                  "--source", str(root / "Demo.java"), "--classpath", str(jar),
                                  "--output-file", str(output)], capture_output=True, text=True)
            self.assertEqual(0, run.returncode, run.stderr)
            markdown = output.read_text(encoding="utf-8")
        self.assertIn('"value": {', markdown)
        self.assertIn('"code":', markdown)

    def test_resolved_nested_duplicate_names_do_not_warn(self):
        outer = Schema("java:a.Outer", "Outer", "a.Outer", "", [Field("user", "b.User", schema_id="java:b.User")])
        user_b = Schema("java:b.User", "User", "b.User", "", [Field("id", "String")])
        user_c = Schema("java:c.User", "User", "c.User", "", [Field("code", "String")])
        endpoint = Endpoint("get", "get", "GET", "/x", [], None, "Outer", "test", response_schema_id="java:a.Outer")
        document = ApiDocument(1, "java", "spring", [endpoint], {item.id: item for item in (outer, user_b, user_c)}).normalized()
        self.assertEqual([], unresolved_types(document.endpoints, document.classes(), document.schemas))


if __name__ == "__main__":
    unittest.main()
