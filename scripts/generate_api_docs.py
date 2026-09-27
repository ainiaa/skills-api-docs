#!/usr/bin/env python3
"""Generate Markdown, Postman and cURL API docs from Spring MVC Java source."""
import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import quote

from api_document_ir import ApiDocument, Endpoint, EnumBinding, EnumOption, Field, ResponseCode, Schema, TypeRef
from discovery import CLASS_KINDS, METHOD_KINDS, SymbolLocation, select_engine
from python_fastapi_adapter import scan_python_document


SCALAR_TYPES = {"String", "CharSequence", "char", "Character", "boolean", "Boolean",
                "byte", "Byte", "short", "Short", "int", "Integer", "long", "Long",
                "float", "Float", "double", "Double", "BigDecimal", "LocalDate",
                "LocalDateTime", "Date", "UUID"}

CONTROLLER_ANNOTATION_PATTERN = re.compile(r"@(RestController|Controller|FeignClient)\b")


def simple_type(type_name: str) -> str:
    return re.sub(r"[\[\]]", "", type_name.split("<", 1)[0].split(".")[-1]).strip()


def generic_argument(type_name: str) -> Optional[str]:
    start = type_name.find("<")
    if start < 0:
        return None
    depth = 0
    for index, character in enumerate(type_name[start:], start):
        if character == "<":
            depth += 1
        elif character == ">":
            depth -= 1
            if depth == 0:
                return type_name[start + 1:index].strip()
    return None


def fields_for(type_name: str, classes: Dict[str, List[Field]]) -> List[Field]:
    argument = generic_argument(type_name)
    return [Field(item.name, re.sub(r"\bT\b", argument, item.type_name) if argument else item.type_name,
                  item.description, item.required, item.notes, item.example, item.location, item.schema_id)
            for item in classes.get(simple_type(type_name), [])]


def parse_classes(roots: List[Path]) -> Dict[str, List[Field]]:
    return scan_java_document(roots).classes()


def referenced_types(type_name: str) -> set:
    return {name for name in re.findall(r"\b[A-Z]\w*\b", type_name)
            if name not in SCALAR_TYPES and name not in {"List", "Set", "Map", "Object", "T"}}


def parse_class_from_jar(jars: List[Path], name: str) -> Tuple[Dict[str, List[Field]], Dict[str, str]]:
    candidates = []
    target = name.replace(".", "/") + ".class"
    for jar in jars:
        with zipfile.ZipFile(jar) as archive:
            entries = [entry for entry in archive.namelist()
                       if entry == target or "." not in name and entry.endswith("/" + target)]
        candidates.extend((jar, entry) for entry in entries)
    if len(candidates) > 1:
        print("Warning: ambiguous JAR DTO type: " + name, file=sys.stderr)
        return {}, {}
    if candidates:
        jar, entry = candidates[0]
        qualified_name = entry[:-6].replace("/", ".")
        output = subprocess.run(["javap", "-classpath", str(jar), "-private", qualified_name],
                                check=True, text=True, capture_output=True).stdout
        fields = []
        for _, modifiers, type_name, field_name in re.findall(
                r"^\s+(?:(private|protected|public)\s+)?((?:(?:static|final|transient|volatile)\s+)*)"
                r"([^;()]+?)\s+(\w+);$", output, re.M):
            if "static" in modifiers.split() or "transient" in modifiers.split():
                continue
            fields.append(Field(field_name, type_name.replace("java.lang.", "")))
        parent = re.search(r"\bextends\s+([\w.$]+(?:<[^>{]+>)?)", output.split("{", 1)[0])
        return {name: fields}, {"parent": parent.group(1) if parent else ""}
    return {}, {}


def merge_jar_schemas(document: ApiDocument, classpath: List[Path]) -> ApiDocument:
    schemas = dict(document.schemas)
    pending = {schema_id for endpoint in document.endpoints
               for schema_id in [endpoint.response_schema_id] +
               [value.schema_id for value in endpoint.parameters +
                ([endpoint.request_body] if endpoint.request_body else [])]
               if schema_id.startswith("java:") and schema_id not in schemas}
    for schema in schemas.values():
        pending.update(value.schema_id for value in schema.fields
                       if value.schema_id.startswith("java:") and value.schema_id not in schemas)
    checked = set()
    while pending:
        schema_id = pending.pop()
        if schema_id in checked or schema_id in schemas:
            continue
        checked.add(schema_id)
        qualified = schema_id.removeprefix("java:")
        parsed, metadata = parse_class_from_jar(classpath, qualified)
        if not parsed:
            continue
        values = parsed[qualified]
        for value in values:
            raw = _leaf_ref(document._parse_type(value.type_name)).name.replace("[]", "")
            if "." in raw and raw.split(".")[-1] not in SCALAR_TYPES:
                value.schema_id = "java:" + raw
                pending.add(value.schema_id)
        parent = metadata.get("parent", "")
        parent_id = "java:" + parent.split("<", 1)[0] if parent else ""
        if parent_id and parent_id not in schemas:
            pending.add(parent_id)
        if parent:
            parent_ref = document._parse_type(parent)
            nested = list(parent_ref.arguments)
            while nested:
                argument = nested.pop()
                nested.extend(argument.arguments)
                if "." in argument.name and simple_type(argument.name) not in SCALAR_TYPES:
                    pending.add("java:" + argument.name)
        schemas[schema_id] = Schema(schema_id, qualified.rsplit(".", 1)[-1], qualified,
                                    parent, values, parent_schema_id=parent_id)
    return ApiDocument(document.ir_version, document.language, document.framework, document.endpoints, schemas).normalized()


def gradle_modules(controller: Path) -> List[Path]:
    module = next((parent for parent in [controller.parent, *controller.parents] if gradle_build_file(parent)), None)
    if module is None:
        return []
    root = next((parent for parent in [module, *module.parents] if gradle_settings_file(parent)), module)
    pending, visited = [module], set()
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        text = gradle_build_file(current).read_text(encoding="utf-8")
        for project_name in re.findall(r"project\(\s*(?:path\s*[:=]\s*)?['\"]:([^'\"]+)", text):
            child = root.joinpath(*project_name.split(":"))
            if gradle_build_file(child):
                pending.append(child)
    return list(visited)


def gradle_build_file(directory: Path) -> Optional[Path]:
    return next((directory / name for name in ("build.gradle", "build.gradle.kts")
                 if (directory / name).is_file()), None)


def gradle_settings_file(directory: Path) -> Optional[Path]:
    return next((directory / name for name in ("settings.gradle", "settings.gradle.kts")
                 if (directory / name).is_file()), None)


def resolved_gradle_source_roots(controller: Path) -> List[Path]:
    return [module / "src/main/java" for module in gradle_modules(controller)
            if (module / "src/main/java").is_dir()]


def resolved_gradle_jars(controller: Path) -> List[Path]:
    coordinates = set()
    for module in gradle_modules(controller):
        text = gradle_build_file(module).read_text(encoding="utf-8")
        coordinates.update(re.findall(r"['\"]([\w.-]+):([\w.-]+):([^'\"]+)['\"]", text))
    cache = Path.home() / ".gradle/caches/modules-2/files-2.1"
    jars = []
    for group, artifact, version in coordinates:
        jars.extend((cache / group / artifact / version).glob("*/*.jar"))
    return jars


def package_root(source_file: Path) -> Optional[Path]:
    """Derive the package source root from a Java file's package declaration."""
    try:
        text = source_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(r"^\s*package\s+([\w.]+)\s*;", text[:4096], re.M)
    segments = match.group(1).split(".") if match else []
    parents = source_file.parents
    if len(parents) <= len(segments):
        return None
    for index, segment in enumerate(reversed(segments)):
        if parents[index].name != segment:
            return None
    return parents[len(segments)]


def is_controller_file(source_file: Path) -> bool:
    try:
        text = source_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return CONTROLLER_ANNOTATION_PATTERN.search(text) is not None


def endpoint_source_file(source: str) -> str:
    """Strip the trailing ":line" the scanner appends to the controller source path."""
    return re.sub(r":\d+$", "", source)


def endpoint_selector_names(selectors: List[str]) -> List[str]:
    names = []
    for selector in selectors:
        name = selector.rsplit("#", 1)[-1].partition("@")[0]
        if name and name not in names:
            names.append(name)
    return names


def controller_candidates(engine, endpoint_names: List[str]) -> Optional[List[Path]]:
    """Controller files covering every endpoint name, or None when one name cannot be resolved."""
    merged: Dict[str, Set[Path]] = {}
    for name in endpoint_names:
        files = {location.path for location in engine.locate(name, METHOD_KINDS)
                 if location.path.is_file() and is_controller_file(location.path)}
        if not files:
            return None
        merged[name] = files
    union: Set[Path] = set()
    for files in merged.values():
        union.update(files)
    return sorted(union, key=str)


def qualified_name_matches(qualified_name: str, package: str, simple: str) -> bool:
    """Match an engine-reported qualified name (e.g. "com.example::Result") against a package."""
    if not qualified_name:
        return True
    return qualified_name.replace("::", ".").startswith(package + ".")


def heal_unresolved_roots(engine, unresolved: List[str], known_roots: Set[Path]) -> Dict[Path, str]:
    """Map unresolved type names to candidate source roots via the discovery engine.

    Package-qualified names are resolved first and filtered by package, so a
    same-simple-name class in an unrelated package cannot seed a wrong root.
    """
    additions: Dict[Path, str] = {}
    for name in sorted(unresolved, key=lambda item: ("." not in item, item)):
        simple = name.rsplit(".", 1)[-1]
        package = name.rsplit(".", 1)[0] if "." in name else ""
        for location in engine.locate(simple, CLASS_KINDS):
            if not location.path.is_file():
                continue
            if package and not qualified_name_matches(location.qualified_name, package, simple):
                continue
            root = package_root(location.path)
            if root is None or root in known_roots or root in additions:
                continue
            additions[root] = name
    return additions


def select_endpoints(document: ApiDocument, selectors: List[str], parser) -> None:
    selected = []
    for selector in selectors:
        selector = selector.rsplit("#", 1)[-1]
        name, separator, route = selector.partition("@")
        method, colon, path = route.partition(":") if separator else ("", "", "")
        if separator and (not colon or not path.startswith("/")):
            parser.error("invalid endpoint selector: " + selector + "; use name@METHOD:/path")
        matches = [endpoint for endpoint in document.endpoints if endpoint.name == name
                   and (not separator or (endpoint.method == method.upper() and endpoint.path == path))]
        if not matches:
            parser.error("endpoint not found: " + selector)
        if len(matches) > 1:
            choices = ", ".join(sorted({f"{item.name}@{item.method}:{item.path}" for item in matches}))
            parser.error("ambiguous endpoint: " + selector + "; use one of: " + choices)
        if matches[0] not in selected:
            selected.append(matches[0])
    document.endpoints = selected


def build_java_document(arguments, roots: List[Path], controller_paths: List[Path],
                        classpath: List[Path], parser) -> Tuple[ApiDocument, Dict[str, List[Field]]]:
    document = scan_java_document(roots, controller_paths or None)
    if arguments.endpoint:
        select_endpoints(document, arguments.endpoint, parser)
    classes = document.classes()
    if classpath:
        document = merge_jar_schemas(document, classpath)
        classes = document.classes()
        classes = merge_jar_classes(classes, document.endpoints, classpath)
        document = document.with_classes({name: fields for name, fields in classes.items()
                                          if name not in document.classes()})
    return document, classes


def affected_endpoints(document: ApiDocument, engine, changed: List[Path]) -> List[Endpoint]:
    """Endpoints whose controller source or transitively referenced DTO types intersect the changed files.

    Schemas are located lazily along each endpoint's reachability traversal, so
    unrelated schemas never trigger engine queries (each query costs a
    subprocess for the codegraph backend).
    """
    changed_paths = {path.resolve() for path in changed}
    locate_cache: Dict[str, List[SymbolLocation]] = {}

    def locate(name: str) -> List[SymbolLocation]:
        if name not in locate_cache:
            locate_cache[name] = engine.locate(name, CLASS_KINDS)
        return locate_cache[name]

    def references_changed_files(seed_ids: List[str]) -> bool:
        reachable, pending = set(), list(seed_ids)
        while pending:
            schema_id = pending.pop()
            if not schema_id or schema_id in reachable:
                continue
            reachable.add(schema_id)
            schema = document.schemas.get(schema_id)
            if schema is None:
                continue
            files = {location.path for location in locate(schema.name) if location.path.is_file()}
            if files & changed_paths:
                return True
            pending.extend(field.schema_id for field in schema.fields if field.schema_id)
            if schema.parent_schema_id:
                pending.append(schema.parent_schema_id)
        return False

    result = []
    for endpoint in document.endpoints:
        if Path(endpoint_source_file(endpoint.source)).resolve() in changed_paths:
            result.append(endpoint)
            continue
        seeds = [endpoint.response_schema_id] + [field.schema_id for field in endpoint.parameters
                                                 + ([endpoint.request_body] if endpoint.request_body else [])]
        if references_changed_files(seeds):
            result.append(endpoint)
            continue
        names = set(referenced_types(endpoint.response_type))
        for field in endpoint.parameters + ([endpoint.request_body] if endpoint.request_body else []):
            names.update(referenced_types(field.type_name))
        if any(location.path in changed_paths
               for name in sorted(names - set(document.classes()))
               for location in locate(name)):
            result.append(endpoint)
    return result


def unresolved_types(endpoints: List[Endpoint], classes: Dict[str, List[Field]],
                     schemas: Optional[Dict[str, Schema]] = None) -> List[str]:
    framework = {"List", "Set", "Map", "Collection", "Iterable", "Optional", "ResponseEntity",
                 "MultipartFile", "HttpServletRequest", "HttpServletResponse", "ServletRequest",
                 "ServletResponse", "Principal", "BindingResult", "Model", "ModelMap"}
    requested = set()
    pending = []
    for endpoint in endpoints:
        pending.extend(referenced_types(endpoint.response_type))
        for parameter in endpoint.parameters + ([endpoint.request_body] if endpoint.request_body else []):
            pending.extend(referenced_types(parameter.type_name))
    while pending:
        name = pending.pop()
        if name in requested or name not in classes:
            requested.add(name)
            continue
        requested.add(name)
        for field in classes[name]:
            pending.extend(referenced_types(field.type_name))
    resolved_ids = {endpoint.response_schema_id for endpoint in endpoints}
    resolved_ids.update(field.schema_id for endpoint in endpoints
                        for field in endpoint.parameters + ([endpoint.request_body] if endpoint.request_body else []))
    source_names = set()
    missing_ids = set()
    missing_parents = set()
    if schemas:
        document = ApiDocument(1, "java", "spring", [], schemas)
        pending_schemas = list(resolved_ids)
        checked_schemas = set()
        while pending_schemas:
            schema_id = pending_schemas.pop()
            if schema_id in checked_schemas:
                continue
            checked_schemas.add(schema_id)
            if schema_id not in schemas:
                if schema_id.startswith("java:") and simple_type(schema_id[5:]) not in SCALAR_TYPES | framework:
                    missing_ids.add(schema_id[5:])
                continue
            schema = schemas[schema_id]
            source_names.add(schema.name)
            pending_schemas.extend(field.schema_id for field in schema.fields if field.schema_id)
            if schema.parent and simple_type(schema.parent) != "Object":
                parent = document._parse_type(schema.parent, schema.parent_schema_id)
                if parent.schema_id in schemas:
                    pending_schemas.append(parent.schema_id)
                else:
                    missing_parents.add(parent.name)
    return sorted({name for name in requested if name not in classes and name not in source_names
                   and name not in framework} | missing_ids | missing_parents)


def scanner_output_dir() -> Path:
    source = Path(__file__).with_name("ApiSaviorAstScanner.java")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
    output = Path(tempfile.gettempdir()) / "api-savior-docs" / digest
    class_file = output / "ApiSaviorAstScanner.class"
    if not class_file.is_file():
        output.mkdir(parents=True, exist_ok=True)
        subprocess.run(["javac", "-source", "11", "-target", "11", "-d", str(output), str(source)],
                       check=True, text=True, capture_output=True)
    return output


def scan_java_document(roots: List[Path], controllers: Optional[List[Path]] = None) -> ApiDocument:
    command = ["java", "-cp", str(scanner_output_dir()), "ApiSaviorAstScanner"]
    for root in roots:
        command.extend(["--source", str(root)])
    for controller in controllers or []:
        command.extend(["--controller", str(controller)])
    result = subprocess.run(command, check=True, text=True, capture_output=True)
    data = json.loads(result.stdout)
    raw_schemas = data["schemas"]

    def fields(values: List[dict]) -> List[Field]:
        return [Field(**value) for value in values]

    endpoints = [Endpoint(
        item["name"], item["notes"], item["method"], item["path"], fields(item["parameters"]),
        Field(**item["request_body"]) if item["request_body"] else None,
        item["response_type"], item["source"], item["content_type"], item.get("response_schema_id", ""),
        item.get("interface_notes", ""), [ResponseCode(**code) for code in item.get("response_codes", [])],
        [EnumBinding(**binding) for binding in item.get("enum_bindings", [])]
    ) for item in data["endpoints"]]
    schemas = {
        item["id"]: Schema(item["id"], item["name"], item["qualified_name"], item["parent"],
                             fields(item["fields"]), item.get("parent_schema_id", ""), item.get("type_parameters", []),
                             [EnumOption(**option) for option in item.get("enum_options", [])],
                             item.get("ignored_properties", []), item.get("allow_getters", False),
                             item.get("allow_setters", False))
        for item in raw_schemas
    }
    document = ApiDocument(data["ir_version"], data["language"], data["framework"],
                           sorted(endpoints, key=lambda item: (item.path, item.method, item.name)), schemas)
    return document.normalized()


def merge_jar_classes(classes: Dict[str, List[Field]], endpoints: List[Endpoint], classpath: List[Path]) -> Dict[str, List[Field]]:
    requested = set()
    for endpoint in endpoints:
        requested.update(referenced_types(endpoint.response_type))
        for parameter in endpoint.parameters + ([endpoint.request_body] if endpoint.request_body else []):
            requested.update(referenced_types(parameter.type_name))
    while requested:
        name = requested.pop()
        if name in classes:
            continue
        parsed, _ = parse_class_from_jar(classpath, name)
        if not parsed:
            continue
        classes.update(parsed)
        for field_value in parsed[name]:
            requested.update(referenced_types(field_value.type_name))
    return classes


def parse_endpoints(roots: List[Path]) -> List[Endpoint]:
    return scan_java_document(roots).endpoints


def example_for(type_name: str, classes: Dict[str, List[Field]], seen: Optional[set] = None):
    seen = seen or set()
    raw = simple_type(type_name)
    if raw in {"List", "Set", "Collection", "Iterable"} or type_name.endswith("[]"):
        return [example_for(generic_argument(type_name) or "String", classes, seen)]
    if raw in {"boolean", "Boolean"}:
        return False
    if raw in {"byte", "Byte", "short", "Short", "int", "Integer", "long", "Long", "float", "Float", "double", "Double", "BigDecimal"}:
        return 1
    if raw in {"Date", "LocalDate", "LocalDateTime"}:
        return "2012-05-28T13:14:00.520+0000"
    if raw in SCALAR_TYPES or raw == "void":
        return "HelloWorld" if raw != "void" else None
    if raw in seen or raw not in classes:
        return {}
    seen.add(raw)
    return {item.name: item.example or example_for(item.type_name, classes, seen.copy())
            for item in fields_for(type_name, classes)}


def field_rows(value: Field, classes: Dict[str, List[Field]], level: int = 1, seen: Optional[set] = None) -> List[Field]:
    rows, seen = [], seen or set()
    raw = simple_type(value.type_name)
    prefix = "" if level < 2 else "&ensp;&ensp;&ensp;&ensp;" * (level - 2) + "└─"
    rows.append(Field(prefix + " " + value.name, value.type_name, value.description,
                      value.required, value.notes, value.example, value.location, value.schema_id))
    nested_type = generic_argument(value.type_name) if raw in {"List", "Set"} else value.type_name
    if nested_type and simple_type(nested_type) not in seen:
        for child in fields_for(nested_type, classes):
            rows.extend(field_rows(child, classes, level + 1, seen | {raw}))
    return rows


def markdown_type(type_name: str) -> str:
    return type_name.replace("<", "\\<").replace(">", "\\>")


def document_rows(values: List[Field], classes: Dict[str, List[Field]]) -> List[Field]:
    result = []
    for value in values:
        raw = simple_type(value.type_name)
        if raw in classes and value.name in {"request", "return"}:
            for child in fields_for(value.type_name, classes):
                result.extend(field_rows(child, classes))
        else:
            result.extend(field_rows(value, classes))
    return result


def _nested_ref(value: TypeRef) -> TypeRef:
    raw = simple_type(value.name)
    if raw in {"Map", "dict"} and len(value.arguments) > 1:
        return value.arguments[1]
    if raw in {"List", "Set", "Collection", "Iterable", "list", "set", "Optional", "Annotated", "ResponseEntity"} and value.arguments:
        return value.arguments[0]
    if raw == "Union":
        return next((item for item in value.arguments if simple_type(item.name) not in {"None", "NoneType"}), value)
    return value


def _leaf_ref(value: TypeRef) -> TypeRef:
    nested = _nested_ref(value)
    return value if nested is value else _leaf_ref(nested)


def schema_known(value: TypeRef, document: ApiDocument) -> bool:
    leaf = _leaf_ref(value)
    return leaf.schema_id in document.schemas if leaf.schema_id else document._schema_for_type(leaf.name) is not None


def example_resolved(value: TypeRef, document: ApiDocument, seen=None) -> bool:
    raw = simple_type(value.name)
    if raw in SCALAR_TYPES | {"str", "int", "float", "bool", "bytes", "date", "datetime",
                              "None", "NoneType", "Any", "Object"}:
        return True
    if raw in {"List", "Set", "Collection", "Iterable", "list", "set", "Map", "dict"}:
        return all(example_resolved(item, document, seen) for item in value.arguments)
    if raw in {"Optional", "Annotated", "Union", "ResponseEntity"}:
        return bool(value.arguments) and example_resolved(_nested_ref(value), document, seen)
    schema = document.schemas.get(value.schema_id) if value.schema_id else document._schema_for_type(value.name)
    if not schema:
        return False
    seen = seen or set()
    key = (schema.id, value.display_name())
    if key in seen:
        return True
    if schema.parent and simple_type(schema.parent) != "Object":
        bindings = dict(zip(schema.type_parameters or (["T"] if value.arguments else []), value.arguments))
        parent = document._substitute(document._parse_type(schema.parent, schema.parent_schema_id), bindings)
        if not example_resolved(parent, document, seen | {key}):
            return False
    return all(example_resolved(document.type_ref(field), document, seen | {key})
               for field in document.fields_for_type(value))


def json_content_type(value: str) -> bool:
    media = (value or "application/json").split(";", 1)[0].strip().lower()
    return media == "application/json" or media.endswith("+json")


def enum_options_for(value: Field, document: ApiDocument) -> Tuple[List[EnumOption], bool]:
    nested = _leaf_ref(document.type_ref(value))
    direct = document.schemas.get(nested.schema_id)
    linked = document.schemas.get(value.enum_schema_id)
    if direct and direct.enum_options:
        return direct.enum_options, False
    if linked and linked.enum_options:
        return linked.enum_options, True
    return [], False


def enum_property(option: EnumOption, hint: str) -> str:
    return next((name for name in option.properties if name.lower() == hint.lower()), "") if hint else ""


def enum_value(option: EnumOption, linked: bool, hint: str = ""):
    selected = enum_property(option, hint) if linked else ""
    if selected:
        return option.properties[selected]
    return option.reference_value if linked else option.api_value


def enum_resolved(option: EnumOption, linked: bool, hint: str = "") -> bool:
    if linked and enum_property(option, hint):
        return True
    return option.reference_resolved if linked else option.value_resolved


def enum_attributes(option: EnumOption, linked: bool, hint: str = "") -> str:
    selected = enum_property(option, hint) if linked else ""
    if selected:
        return "；".join(f"{name}={value}" for name, value in option.properties.items()
                        if name not in {selected, option.description_property})
    return option.reference_attributes if linked else option.attributes


def typed_example(type_name: str, value):
    raw = simple_type(type_name)
    try:
        if raw in {"byte", "Byte", "short", "Short", "int", "Integer", "long", "Long"}:
            return int(value)
        if raw in {"float", "Float", "double", "Double", "BigDecimal"}:
            return float(value)
        if raw in {"boolean", "Boolean"}:
            if str(value).lower() in {"true", "false"}:
                return str(value).lower() == "true"
            return None
        return str(value)
    except (TypeError, ValueError):
        return None


def meaningful_string(value: Field) -> str:
    meaning = value.description or value.name or "请填写"
    for separator in ("（", "(", "，", ",", "。", "\n"):
        meaning = meaning.split(separator, 1)[0]
    return "<" + meaning.strip() + ">"


def example_for_field(value: Field, document: ApiDocument, seen: Optional[set] = None):
    if value.example is not None:
        declared = typed_example(value.type_name, value.example) if document.language == "java" else value.example
        if declared is not None:
            return declared
    type_ref = document.type_ref(value)
    if value.type_name.strip().endswith("[]") or simple_type(type_ref.name) in {"List", "Set", "Collection", "Iterable", "list", "set", "Map", "dict"}:
        options, linked = enum_options_for(value, document)
        if options and simple_type(type_ref.name) in {"List", "Set", "Collection", "Iterable", "list", "set"}:
            first = options[0]
            if enum_resolved(first, linked, value.enum_value_hint):
                return [enum_value(first, linked, value.enum_value_hint)]
        return example_for_ref(type_ref, document, seen)
    options, linked = enum_options_for(value, document)
    if options:
        first = options[0]
        if enum_resolved(first, linked, value.enum_value_hint):
            candidate = enum_value(first, linked, value.enum_value_hint)
            if not linked:
                return candidate
            compatible = typed_example(value.type_name, candidate)
            if compatible is not None:
                return compatible
        if document.language != "java":
            return None
        if not linked:
            return meaningful_string(value)
    if document.language == "java":
        raw = simple_type(value.type_name)
        if raw in {"String", "CharSequence", "char", "Character"}:
            return meaningful_string(value)
        if raw in {"byte", "Byte", "short", "Short", "int", "Integer", "long", "Long",
                   "float", "Float", "double", "Double", "BigDecimal"}:
            if raw in {"long", "Long"} and ("time" in value.name.lower() or value.name.lower().startswith("date")
                                                or "毫秒" in value.description):
                return 1700000000000
            return value.minimum if value.minimum is not None else 0
    return example_for_ref(document.type_ref(value), document, seen)


def example_for_ref(value: TypeRef, document: ApiDocument, seen: Optional[set] = None):
    seen = seen or set()
    raw = simple_type(value.name)
    schema = document.schemas.get(value.schema_id)
    if schema and schema.enum_options:
        first = schema.enum_options[0]
        return first.api_value if first.value_resolved else ("<请填写>" if document.language == "java" else None)
    if raw in {"List", "Set", "Collection", "Iterable", "list", "set"}:
        nested = _nested_ref(value)
        return [] if nested is value else [example_for_ref(nested, document, seen)]
    if raw in {"Map", "dict"}:
        nested = _nested_ref(value)
        return {"key": example_for_ref(nested, document, seen) if nested is not value
                else ("<请填写>" if document.language == "java" else "HelloWorld")}
    if raw in {"Optional", "Annotated", "Union", "ResponseEntity"}:
        nested = _nested_ref(value)
        return {} if nested is value else example_for_ref(nested, document, seen)
    if raw in {"boolean", "Boolean", "bool"}:
        return False
    if raw in {"byte", "Byte", "short", "Short", "int", "Integer", "long", "Long", "float", "Float", "double", "Double", "BigDecimal"}:
        return 0 if document.language == "java" else 1
    if raw in {"Date", "LocalDate", "LocalDateTime", "date", "datetime"}:
        return "2012-05-28T13:14:00.520+0000"
    if raw in SCALAR_TYPES | {"str", "bytes", "UUID", "void", "None", "NoneType"}:
        if raw in {"void", "None", "NoneType"}:
            return None
        return "<请填写>" if document.language == "java" else "HelloWorld"
    key = value.schema_id or value.display_name()
    if key in seen:
        return {}
    fields = document.fields_for_type(value)
    if not fields:
        return {}
    return {item.wire_name or item.name: example_for_field(item, document, seen | {key})
            for item in fields}


def field_rows_ref(value: Field, document: ApiDocument, level: int = 1, seen: Optional[set] = None) -> List[Field]:
    rows, seen = [], seen or set()
    type_ref = document.type_ref(value)
    prefix = "" if level < 2 else "&ensp;&ensp;&ensp;&ensp;" * (level - 2) + "└─"
    rows.append(Field(prefix + " " + (value.wire_name or value.name), value.type_name, value.description,
                      value.required, value.notes, value.example, value.location, value.schema_id, type_ref,
                      value.enum_schema_id, value.minimum, value.enum_value_hint, value.wire_name))
    nested = _leaf_ref(type_ref)
    key = nested.schema_id or nested.display_name()
    if key not in seen:
        for child in document.fields_for_type(nested):
            rows.extend(field_rows_ref(child, document, level + 1, seen | {key}))
    return rows


def document_rows_ref(values: List[Field], document: ApiDocument) -> List[Field]:
    result = []
    for value in values:
        type_ref = document.type_ref(value)
        nested = _leaf_ref(type_ref) if value.name in {"request", "return"} else type_ref
        if value.name in {"request", "return"} and document.fields_for_type(nested):
            for child in document.fields_for_type(nested):
                result.extend(field_rows_ref(child, document))
        else:
            result.extend(field_rows_ref(value, document))
    return result


def markdown_cell(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def field_notes(value: Field, document: ApiDocument) -> str:
    options, linked = enum_options_for(value, document)
    parts = [value.notes] if value.notes else []
    if options:
        labels = []
        for option in options:
            if enum_resolved(option, linked, value.enum_value_hint):
                api_value = enum_value(option, linked, value.enum_value_hint)
                label = str(api_value)
                if option.description:
                    label += f"：{option.description}"
                if enum_attributes(option, linked, value.enum_value_hint):
                    label += f"（{enum_attributes(option, linked, value.enum_value_hint)}）"
                if not linked and option.member_name != str(api_value):
                    label = f"{option.member_name}（{label}）"
            else:
                label = option.member_name + "（取值未解析）"
            labels.append(label)
        parts.append("枚举取值：" + "；".join(labels))
    return markdown_cell("；".join(parts))


def enum_tables(output: List[str], request_rows: List[Field], response_rows: List[Field],
                request_document: ApiDocument, response_document: ApiDocument) -> None:
    groups = []
    for title, rows, document in (("入参", request_rows, request_document),
                                  ("出参", response_rows, response_document)):
        for row in rows:
            options, linked = enum_options_for(row, document)
            if options:
                groups.append((title, row.name.rsplit("└─", 1)[-1].replace("&ensp;", "").strip(),
                               options, linked, row.enum_value_hint))
    if not groups:
        return
    output.extend(["", "## 枚举说明", ""])
    for title, name, options, linked, hint in groups:
        output.extend([f"### {title} {name}", "", "| 枚举成员 | 取值 | 含义 | 其他属性 |",
                       "| --- | --- | --- | --- |"])
        for option in options:
            api_value = markdown_cell(enum_value(option, linked, hint)) if enum_resolved(option, linked, hint) else "-"
            output.append(f"| {markdown_cell(option.member_name)} | {api_value} | {markdown_cell(option.description)} | {markdown_cell(enum_attributes(option, linked, hint) or '-')} |")
        output.append("")


def bulk_values(values: List[Field], document: ApiDocument) -> List[Tuple[str, str, bool]]:
    result: List[Tuple[str, str, bool]] = []

    def visit(value: Field, name: str, seen: set) -> None:
        type_ref = document.type_ref(value)
        key = type_ref.schema_id or type_ref.display_name()
        children = [] if key in seen else document.fields_for_type(type_ref)
        if children:
            for child in children:
                visit(child, name + "." + (child.wire_name or child.name), seen | {key})
            return
        example = example_for_field(value, document)
        if isinstance(example, list):
            for index, item in enumerate(example):
                key = name if value.location in {"query", "file"} else f"{name}[{index}]"
                result.append((key, str(item), value.required))
        elif isinstance(example, dict):
            result.append((name, "{}", value.required))
        else:
            result.append((name, str(example).lower() if isinstance(example, bool) else str(example), value.required))

    for field in values:
        visit(field, field.wire_name or field.name, set())
    return result


def request_url(endpoint: Endpoint, document: ApiDocument, base_url: str) -> str:
    url = base_url.rstrip("/") + endpoint.path

    def encode(value: str) -> str:
        return value if value.startswith("<") and value.endswith(">") else quote(value, safe="")

    for field in endpoint.parameters:
        if field.location == "path":
            name = field.wire_name or field.name
            url = re.sub(r"\{" + re.escape(name) + r"(?::[^}]+)?\}",
                         lambda _: encode(str(example_for_field(field, document))), url)
    query = bulk_values([field for field in endpoint.parameters if field.location in {"", "query"}], document)
    if query:
        url += "?" + "&".join(quote(name, safe="[].") + "=" + encode(value)
                                    for name, value, _ in query)
    return url


def render_markdown(document: ApiDocument, base_url: str) -> str:
    document = document.normalized()
    output = []
    for endpoint in document.endpoints:
        endpoint_document = document.for_endpoint(endpoint)
        endpoint = endpoint_document.endpoints[0]
        request_document = endpoint_document.for_direction("request")
        response_document = endpoint_document.for_direction("response")
        url = request_url(endpoint, request_document, base_url)
        output.append(f"# {endpoint.notes}")
        if endpoint.interface_notes:
            output.append("> " + endpoint.interface_notes)
        output.extend(["", "## 请求信息", "", "### 请求地址", "```", url, "```",
                       "", "### 请求方法", "```", endpoint.method, "```", ""])
        if endpoint.content_type and endpoint.method != "GET":
            output.extend(["### 请求体类型", "```", endpoint.content_type, "```", ""])
        output.extend(["## 入参"])
        request_fields = endpoint.parameters + ([endpoint.request_body] if endpoint.request_body else [])
        has_request_example = False
        if request_fields:
            if endpoint.request_body:
                example = example_for_field(endpoint.request_body, request_document)
                request_ref = request_document.type_ref(endpoint.request_body)
                known = example_resolved(request_ref, request_document)
                if json_content_type(endpoint.content_type) and known and (example != {} or schema_known(request_ref, request_document)):
                    output.extend(["### 请求结构示例 (RequestBody)", "> 占位值需替换为符合接口校验和当前环境主数据的真实值。", "",
                                   "```json", json.dumps(example, ensure_ascii=False, indent=2), "```", ""])
                    has_request_example = True
            else:
                bulk = bulk_values(endpoint.parameters, request_document)
                if bulk:
                    output.extend(["### 入参示例 (Postman Bulk Edit)", "```json"])
                    output.extend(("" if required else "//") + name + ":" + value
                                  for name, value, required in bulk)
                    output.extend(["```", ""])
                    has_request_example = True
            if not has_request_example:
                if endpoint.request_body:
                    message = (f"请求体类型 {markdown_cell(endpoint.request_body.type_name)} 未解析，无法生成示例"
                               if not example_resolved(request_document.type_ref(endpoint.request_body), request_document)
                               else "非 JSON 请求体，无法生成 JSON 示例")
                    output.extend(["> " + message, ""])
            rows = document_rows_ref(request_fields, request_document)
            if rows:
                output.extend(["### 入参字段说明", "", "| **字段** | **类型** | **必填** | **含义** | **其他参考信息** |",
                               "| -------- | -------- | -------- | -------- | -------- |"])
                for item in rows:
                    output.append(f"|{markdown_cell(item.name)}     | **{markdown_cell(markdown_type(item.type_name))}**     | {'**是**' if item.required else '否'}  |  {markdown_cell(item.description)} | {field_notes(item, request_document)}  |")
        else:
            output.extend(["> 此接口无任何入参", ""])
        output.extend(["", "## 出参"])
        if not endpoint.response_type:
            output.extend(["> 未声明出参类型，无法生成示例", ""])
        else:
            response = example_for_ref(response_document.response_ref(endpoint), response_document)
            response_ref = response_document.response_ref(endpoint)
            if response is not None and example_resolved(response_ref, response_document) and (response != {} or schema_known(response_ref, response_document)):
                output.extend(["### 出参示例", "```json", json.dumps(response, ensure_ascii=False, indent=2), "```", ""])
            else:
                if endpoint.response_type in {"void", "None", "NoneType"}:
                    output.extend(["> 此接口无任何出参", ""])
                else:
                    output.extend([f"> 出参类型 {markdown_cell(endpoint.response_type)} 未解析，无法生成示例", ""])
        rows = [] if endpoint.response_type in {"", "void", "None", "NoneType"} else document_rows_ref(
            [Field("return", endpoint.response_type, schema_id=endpoint.response_schema_id)], response_document)
        if rows:
            output.extend(["### 出参字段说明", "", "| **字段** | **类型**  | **含义** | **其他参考信息** |",
                           "| -------- | -------- | -------- | -------- |"])
            for item in rows:
                output.append(f"|{markdown_cell(item.name)}     | **{markdown_cell(markdown_type(item.type_name))}**    |  {markdown_cell(item.description)} | {field_notes(item, response_document)}  |")
        enum_tables(output, document_rows_ref(request_fields, request_document), rows,
                    request_document, response_document)
        if endpoint.response_codes:
            output.extend(["## 更多信息", "### Code 更多含义", "", "| Code | 含义 |", "| -------- | -------- |"])
            output.extend(f"| **{markdown_cell(code.code)}** | {markdown_cell(code.message)} |"
                          for code in endpoint.response_codes)
        output.append("")
    return "\n".join(output)


def _postman_item(endpoint: Endpoint, document: ApiDocument, base_url: str) -> dict:
    url = request_url(endpoint, document, base_url)
    request = {"method": endpoint.method, "header": [], "url": url}
    query = bulk_values([field for field in endpoint.parameters if field.location in {"", "query"}], document)
    form = bulk_values([field for field in endpoint.parameters if field.location in {"form", "file", "RequestPart"}], document)
    if query and not endpoint.request_body:
        request["url"] = {"raw": url, "query": [
            {"key": name, "value": value, "disabled": not required}
            for name, value, required in query]}
    for field in endpoint.parameters:
        if field.location == "header":
            request["header"].append({"key": field.wire_name or field.name,
                                      "value": str(example_for_field(field, document))})
    cookies = [(field.wire_name or field.name) + "=" + str(example_for_field(field, document))
               for field in endpoint.parameters if field.location == "cookie"]
    if cookies:
        request["header"].append({"key": "Cookie", "value": "; ".join(cookies)})
    if endpoint.request_body:
        content_type = endpoint.content_type or "application/json"
        example = example_for_field(endpoint.request_body, document)
        request_ref = document.type_ref(endpoint.request_body)
        if json_content_type(content_type) and example_resolved(request_ref, document) and (example != {} or schema_known(request_ref, document)):
            request["header"].append({"key": "Content-Type", "value": content_type})
            request["body"] = {"mode": "raw", "raw": json.dumps(example, ensure_ascii=False, indent=2)}
    elif form:
        if endpoint.content_type == "multipart/form-data":
            file_names = {field.wire_name or field.name for field in endpoint.parameters if field.location == "file"}
            request["body"] = {"mode": "formdata", "formdata": [
                ({"key": name, "src": "/path/to/file", "type": "file", "disabled": not required}
                 if any(name == file_name or name.startswith(file_name + "[") for file_name in file_names) else
                 {"key": name, "value": value, "type": "text", "disabled": not required})
                for name, value, required in form]}
        elif endpoint.content_type == "application/x-www-form-urlencoded":
            request["body"] = {"mode": "urlencoded", "urlencoded": [
                {"key": name, "value": value, "disabled": not required}
                for name, value, required in form]}
    return {"name": endpoint.notes, "request": request, "response": []}


def render_postman(document: ApiDocument, base_url: str) -> dict:
    document = document.normalized()
    items = []
    for endpoint in document.endpoints:
        specialized = document.for_endpoint(endpoint)
        items.append(_postman_item(specialized.endpoints[0], specialized.for_direction("request"), base_url))
    return {"info": {"name": "API Savior", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
            "item": items}


def render_curl(document: ApiDocument, base_url: str) -> str:
    document = document.normalized()
    result = ["#!/usr/bin/env sh", "set -eu", ""]
    for endpoint in document.endpoints:
        endpoint_document = document.for_endpoint(endpoint).for_direction("request")
        endpoint = endpoint_document.endpoints[0]
        url = request_url(endpoint, endpoint_document, base_url or
                          ("http://localhost:8000" if document.language == "python" else "http://localhost:8080"))
        command = ["curl", "-X", endpoint.method, shlex.quote(url)]
        for field in endpoint.parameters:
            if field.location == "header":
                command += ["-H", shlex.quote((field.wire_name or field.name) + ": " + str(example_for_field(field, endpoint_document)))]
            elif field.location == "cookie":
                command += ["-b", shlex.quote((field.wire_name or field.name) + "=" + str(example_for_field(field, endpoint_document)))]
        if endpoint.request_body:
            content_type = endpoint.content_type or "application/json"
            example = example_for_field(endpoint.request_body, endpoint_document)
            request_ref = endpoint_document.type_ref(endpoint.request_body)
            if json_content_type(content_type) and example_resolved(request_ref, endpoint_document) and (example != {} or schema_known(request_ref, endpoint_document)):
                command += ["-H", shlex.quote("Content-Type: " + content_type), "--data",
                            shlex.quote(json.dumps(example, ensure_ascii=False))]
        else:
            parameters = bulk_values([item for item in endpoint.parameters if item.location in {"form", "file", "RequestPart"}], endpoint_document)
            if endpoint.content_type == "multipart/form-data":
                file_names = {field.wire_name or field.name for field in endpoint.parameters if field.location == "file"}
                for name, value, _ in parameters:
                    is_file = any(name == file_name or name.startswith(file_name + "[") for file_name in file_names)
                    command += ["-F" if is_file else "--form-string",
                                shlex.quote(name + "=" + ("@/path/to/file" if is_file else value))]
            elif endpoint.content_type == "application/x-www-form-urlencoded":
                for name, value, _ in parameters:
                    command += ["--data-urlencode", shlex.quote(name + "=" + value)]
        result.extend([*("# " + line for line in endpoint.notes.splitlines()), " ".join(command), ""])
    return "\n".join(result)


def endpoint_values(endpoint: Endpoint) -> List[Field]:
    values = endpoint.parameters + ([endpoint.request_body] if endpoint.request_body else [])
    return values + [Field("return", endpoint.response_type, schema_id=endpoint.response_schema_id)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=("java", "python"), default="java")
    parser.add_argument("--source", action="append", required=True, type=Path, help="Source root; repeat as needed")
    parser.add_argument("--output", type=Path, help="Directory for api-docs.md, Postman collection, and cURL script")
    parser.add_argument("--output-file", type=Path, help="Markdown file for the selected endpoint(s)")
    parser.add_argument("--endpoint", action="append", help="Method name or name@METHOD:/path; repeat as needed")
    parser.add_argument("--controller", action="append", type=Path, help="Controller source file for fast single-endpoint generation")
    parser.add_argument("--classpath", action="append", type=Path, help="Dependency JAR used when a DTO is not in source")
    parser.add_argument("--changed", action="append", type=Path, help="Changed source file; regenerate only the endpoints it affects (requires a code discovery index)")
    parser.add_argument("--no-codegraph", action="store_true", help="Disable the optional code discovery engine (.codegraph)")
    parser.add_argument("--base-url", default="")
    arguments = parser.parse_args()
    if not arguments.output and not arguments.output_file:
        parser.error("one of --output or --output-file is required")
    roots = [path.resolve() for path in arguments.source]
    missing = [str(path) for path in roots if not path.exists()]
    if missing:
        parser.error("Source root does not exist: " + ", ".join(missing))
    controller_paths = [path.resolve() for path in arguments.controller or []]
    missing = [str(path) for path in controller_paths if not path.is_file()]
    if missing:
        parser.error("Controller source does not exist: " + ", ".join(missing))
    if controller_paths:
        if arguments.language != "java":
            parser.error("--controller is currently supported only for --language java")
        roots = list(dict.fromkeys(roots + resolved_gradle_source_roots(controller_paths[0])))
    classpath = [path.resolve() for path in arguments.classpath or []]
    missing = [str(path) for path in classpath if not path.is_file()]
    if missing:
        parser.error("Classpath JAR does not exist: " + ", ".join(missing))
    if arguments.changed and arguments.language != "java":
        parser.error("--changed is currently supported only for --language java")
    if arguments.changed and arguments.endpoint:
        parser.error("--changed cannot be combined with --endpoint")
    engine = select_engine(roots, enabled=not arguments.no_codegraph) if arguments.language == "java" else None
    if engine and arguments.endpoint and not controller_paths:
        names = endpoint_selector_names(arguments.endpoint)
        candidates = controller_candidates(engine, names)
        if candidates:
            print(f"[{engine.name}] narrowed scan to {len(candidates)} controller file(s) for: " + ", ".join(names),
                  file=sys.stderr)
            controller_paths = candidates
            roots = list(dict.fromkeys(roots + [root for controller in candidates
                                                for root in resolved_gradle_source_roots(controller)]))
    if controller_paths and not classpath:
        classpath = resolved_gradle_jars(controller_paths[0])
    if arguments.language == "java":
        scan_roots: List[Path] = list(roots)
        added_roots: Set[Path] = set()
        for attempt in range(3):
            document, classes = build_java_document(arguments, scan_roots, controller_paths, classpath, parser)
            unresolved = unresolved_types(document.endpoints, classes, document.schemas)
            if engine is None or not unresolved or attempt == 2:
                break
            additions = heal_unresolved_roots(engine, unresolved, set(scan_roots) | added_roots)
            if not additions:
                break
            for root, name in sorted(additions.items(), key=lambda item: str(item[0])):
                print(f"[{engine.name}] auto-added source root {root} for {name}", file=sys.stderr)
            added_roots.update(additions)
            scan_roots.extend(sorted(additions, key=str))
        if arguments.changed:
            if engine is None:
                parser.error("--changed requires a discovery engine; install codegraph "
                             "(and run `codegraph init`) or the tree-sitter packages "
                             "(pip3 install tree-sitter tree-sitter-python tree-sitter-java)")
            affected = affected_endpoints(document, engine, arguments.changed)
            if not affected:
                print("No endpoints affected by the changed files")
                return 0
            document.endpoints = affected
            unresolved = unresolved_types(document.endpoints, classes, document.schemas)
    else:
        if classpath:
            parser.error("--classpath is currently supported only for --language java")
        document = scan_python_document(roots)
        if arguments.endpoint:
            select_endpoints(document, arguments.endpoint, parser)
        classes = document.classes()
        unresolved = unresolved_types(document.endpoints, classes, document.schemas)
    if unresolved:
        print("Warning: unresolved DTO types: " + ", ".join(unresolved), file=sys.stderr)
    markdown = render_markdown(document, arguments.base_url)
    if arguments.output:
        arguments.output.mkdir(parents=True, exist_ok=True)
        (arguments.output / "api-docs.md").write_text(markdown, encoding="utf-8")
        collection = render_postman(document, arguments.base_url)
        (arguments.output / "postman-collection.json").write_text(json.dumps(collection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        curl_path = arguments.output / "curl.sh"
        curl_path.write_text(render_curl(document, arguments.base_url), encoding="utf-8")
        curl_path.chmod(0o755)
    if arguments.output_file:
        arguments.output_file.parent.mkdir(parents=True, exist_ok=True)
        arguments.output_file.write_text(markdown, encoding="utf-8")
    print(f"Generated {len(document.endpoints)} endpoint(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
