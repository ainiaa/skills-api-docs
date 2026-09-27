"""FastAPI source adapter using only Python's standard-library AST."""
import ast
import os
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from api_document_ir import ApiDocument, Endpoint, Field, Schema


HTTP_METHODS = {"get": "GET", "head": "HEAD", "options": "OPTIONS", "post": "POST",
                "put": "PUT", "patch": "PATCH", "delete": "DELETE", "trace": "TRACE"}
SCALARS = {"str", "int", "float", "bool", "bytes", "UUID", "date", "datetime"}
PARAMETER_MARKERS = {"Path", "Query", "Header", "Cookie", "Body", "Form", "File"}


def python_files(roots: List[Path]) -> Iterable[Path]:
    seen = set()
    for root in roots:
        if root.is_file() and root.suffix == ".py":
            if root.resolve() not in seen:
                seen.add(root.resolve())
                yield root
        elif root.is_dir():
            for current, directories, files in os.walk(root):
                directories[:] = sorted(name for name in directories
                                        if name not in {".venv", "venv", "__pycache__", ".git"})
                for name in sorted(files):
                    if name.endswith(".py"):
                        path = Path(current) / name
                        if path.resolve() not in seen:
                            seen.add(path.resolve())
                            yield path


def source_text(node) -> str:
    return ast.unparse(node) if node is not None else ""


def module_name(path: Path, roots: List[Path]) -> str:
    root = next((item for item in roots if item.is_dir() and path.is_relative_to(item)), path.parent)
    if (root / "__init__.py").is_file():
        root = root.parent
    parts = path.relative_to(root).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def join_path(*parts: str) -> str:
    return "/" + "/".join(part.strip("/") for part in parts if part).strip("/")


def decorator_mapping(decorator, resolve):
    if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
        return None
    method = HTTP_METHODS.get(decorator.func.attr)
    if not method and decorator.func.attr != "api_route":
        return None
    path = decorator.args[0] if decorator.args else next((item.value for item in decorator.keywords if item.arg == "path"), None)
    path_value = resolve(path)
    if not isinstance(path_value, str):
        return None
    methods = [method] if method else []
    if decorator.func.attr == "api_route":
        declared = next((item.value for item in decorator.keywords if item.arg == "methods"), None)
        if declared is None or isinstance(declared, ast.Constant) and declared.value is None:
            methods = ["GET"]
        else:
            declared_methods = resolve(declared)
            if isinstance(declared_methods, (list, tuple, set)):
                methods = [item.upper() for item in declared_methods
                           if isinstance(item, str) and item.upper() in HTTP_METHODS.values()]
        if not methods:
            return None
    owner = source_text(decorator.func.value) if isinstance(decorator.func.value, (ast.Name, ast.Attribute)) else ""
    return methods, path_value, owner, decorator


def module_constants(tree: ast.Module) -> dict:
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    values[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            values[node.target.id] = node.value
    return values


def resolve_reference(name: str, module: str, bindings: Dict[str, str]) -> str:
    first, dot, rest = name.partition(".")
    return bindings.get(first, module + "." + first) + (dot + rest if dot else "")


def constants_before(tree: ast.Module, module: str, constants: dict, statement) -> dict:
    local_names = {module + "." + name for name in module_constants(tree)}
    scoped = {name: value for name, value in constants.items() if name not in local_names}
    prior = ast.Module(body=tree.body[:tree.body.index(statement)], type_ignores=[])
    scoped.update({module + "." + name: value for name, value in module_constants(prior).items()})
    return scoped


def constant_value(node, module: str, bindings: Dict[str, str], constants: dict,
                   bindings_by_module=None, seen=None):
    seen = seen or set()
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [constant_value(item, module, bindings, constants, bindings_by_module, seen) for item in node.elts]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = constant_value(node.left, module, bindings, constants, bindings_by_module, seen)
        right = constant_value(node.right, module, bindings, constants, bindings_by_module, seen)
        return left + right if isinstance(left, str) and isinstance(right, str) else None
    if isinstance(node, (ast.Name, ast.Attribute)):
        name = source_text(node)
        qualified = resolve_reference(name, module, bindings)
        if qualified in seen or qualified not in constants:
            return None
        target_module = qualified.rsplit(".", 1)[0]
        target_bindings = (bindings_by_module or {}).get(target_module, {})
        return constant_value(constants[qualified], target_module, target_bindings,
                              constants, bindings_by_module, seen | {qualified})
    return None


def import_bindings(tree: ast.Module, module: str, is_package: bool = False) -> Dict[str, str]:
    bindings = {}
    package = module.split(".") if is_package else module.split(".")[:-1]
    for node in tree.body:
        if isinstance(node, ast.Import):
            for item in node.names:
                bindings[item.asname or item.name.split(".")[0]] = (
                    item.name if item.asname else item.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                base = ".".join(package[:len(package) - node.level + 1] + ([base] if base else []))
            for item in node.names:
                if item.name != "*":
                    bindings[item.asname or item.name] = ".".join(part for part in (base, item.name) if part)
    return bindings


def fastapi_instances(tree: ast.Module, bindings: Dict[str, str], resolve) -> Tuple[Dict[str, str], set]:
    prefixes, apps = {}, set()
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or not isinstance(node.value, ast.Call):
            continue
        constructor = source_text(node.value.func)
        resolved = bindings.get(constructor, constructor)
        if "." in constructor:
            module_alias, class_name = constructor.rsplit(".", 1)
            if bindings.get(module_alias) == "fastapi":
                resolved = "fastapi." + class_name
        if resolved not in {"fastapi.APIRouter", "fastapi.FastAPI"}:
            continue
        prefix_node = next((keyword.value for keyword in node.value.keywords if keyword.arg == "prefix"), None)
        prefix = resolve(prefix_node, node) if prefix_node is not None else ""
        for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
            if isinstance(target, ast.Name):
                if resolved == "fastapi.APIRouter":
                    if isinstance(prefix, str):
                        prefixes[target.id] = prefix
                else:
                    apps.add(target.id)
    return prefixes, apps


def call_name(call: ast.Call, bindings=None) -> str:
    name = source_text(call.func)
    first, dot, rest = name.partition(".")
    resolved = (bindings or {}).get(first, first) + (dot + rest if dot else "")
    if resolved.startswith("fastapi.") or resolved.startswith("fastapi.params."):
        return resolved.split(".")[-1]
    return name.split(".")[-1] if not bindings else ""


def parameter_location(default, bindings=None):
    if not isinstance(default, ast.Call):
        return "query"
    return {"Path": "path", "Header": "header", "Cookie": "cookie", "Body": "body", "Form": "form", "File": "file"}.get(call_name(default, bindings), "query")


def annotation_parameter(annotation, bindings: Dict[str, str]):
    if not isinstance(annotation, ast.Subscript):
        return annotation, None
    annotation_name = source_text(annotation.value)
    resolved = bindings.get(annotation_name, annotation_name)
    if "." in annotation_name:
        module_alias, name = annotation_name.rsplit(".", 1)
        resolved = bindings.get(module_alias, module_alias) + "." + name
    if resolved not in {"typing.Annotated", "typing_extensions.Annotated"}:
        return annotation, None
    items = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
    marker = next((item for item in items[1:] if isinstance(item, ast.Call)
                   and call_name(item, bindings) in PARAMETER_MARKERS | {"Depends"}), None)
    return items[0], marker


def marker_default(marker, bindings=None):
    if not isinstance(marker, ast.Call) or call_name(marker, bindings) not in PARAMETER_MARKERS:
        return marker
    if marker.args:
        return marker.args[0]
    return next((keyword.value for keyword in marker.keywords if keyword.arg == "default"), None)


def is_required(default, bindings=None) -> bool:
    if default is None or isinstance(default, ast.Constant) and default.value is Ellipsis:
        return True
    if isinstance(default, ast.Call) and call_name(default, bindings) in PARAMETER_MARKERS:
        value = marker_default(default, bindings)
        return value is None or isinstance(value, ast.Constant) and value.value is Ellipsis
    return False


def literal_default(default, bindings=None):
    value = marker_default(default, bindings)
    if value is None:
        return None
    try:
        result = ast.literal_eval(value)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return None
    return result if result is not Ellipsis else None


def type_names(annotation: str) -> List[str]:
    return [name.split(".")[-1] for name in re.findall(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", annotation)]


def resolve_schema_id(annotation: str, module: str, bindings: Dict[str, str], by_name: Dict[str, List[Schema]], schemas: Dict[str, Schema]) -> str:
    for dotted in re.findall(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+", annotation):
        first, rest = dotted.split(".", 1)
        imported = bindings.get(first)
        if imported and "python:" + imported + "." + rest in schemas:
            return "python:" + imported + "." + rest
    for name in type_names(annotation):
        imported = bindings.get(name)
        if imported and "python:" + imported in schemas:
            return "python:" + imported
        same_module = "python:" + module + "." + name
        if same_module in schemas:
            return same_module
        matches = by_name.get(name, [])
        if len(matches) == 1:
            return matches[0].id
    return ""


def route_prefixes(units: List[Tuple[Path, ast.Module, str]], constants: dict,
                   bindings_by_module: Dict[str, Dict[str, str]]):
    router_prefix, includes, constructors, apps = {}, {}, {}, set()
    for path, tree, module in units:
        bindings = import_bindings(tree, module, path.name == "__init__.py")
        resolve = lambda value, statement: constant_value(
            value, module, bindings, constants_before(tree, module, constants, statement), bindings_by_module)
        routers, module_apps = fastapi_instances(tree, bindings, resolve)
        apps.update(module + "." + name for name in module_apps)
        for name, prefix in routers.items():
            router_prefix[module + "." + name] = prefix
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)) or not isinstance(node.value, ast.Call):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and (target.id in routers or target.id in module_apps):
                    constructors[module + "." + target.id] = dependency_calls(
                        node.value, bindings, module, constants_before(tree, module, constants, node), bindings_by_module)
        for node in tree.body:
            if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
                continue
            call = node.value
            if not isinstance(call.func, ast.Attribute) or call.func.attr != "include_router":
                continue
            router = call.args[0] if call.args else next(
                (keyword.value for keyword in call.keywords if keyword.arg == "router"), None)
            if not isinstance(router, (ast.Name, ast.Attribute)):
                continue
            child = resolve_reference(source_text(router), module, bindings)
            prefix_node = next((keyword.value for keyword in call.keywords if keyword.arg == "prefix"), None)
            prefix = resolve(prefix_node, node) if prefix_node is not None else ""
            if not isinstance(prefix, str):
                continue
            parent = resolve_reference(source_text(call.func.value), module, bindings)
            includes.setdefault(parent, []).append((child, prefix, dependency_calls(
                call, bindings, module, constants_before(tree, module, constants, node), bindings_by_module)))

    effective = {}

    def visit(router: str, prefix: str, inherited: list, seen: set):
        if router in seen:
            return
        full_prefix = join_path(prefix, router_prefix.get(router, "")) if router not in apps else prefix
        dependencies = inherited + constructors.get(router, [])
        effective.setdefault(router, []).append((full_prefix, dependencies))
        for child, child_prefix, child_dependencies in includes.get(router, []):
            visit(child, join_path(full_prefix, child_prefix), dependencies + child_dependencies, seen | {router})

    included = {child for children in includes.values() for child, _, _ in children}
    for root in sorted((set(router_prefix) | apps) - included):
        visit(root, "", [], set())
    return effective


def dependency_calls(call: ast.Call, bindings: Dict[str, str], module: str, constants: dict,
                     bindings_by_module: Dict[str, Dict[str, str]]):
    declared = next((keyword.value for keyword in call.keywords if keyword.arg == "dependencies"), None)
    seen = set()
    while isinstance(declared, (ast.Name, ast.Attribute)):
        name = source_text(declared)
        first, dot, rest = name.partition(".")
        qualified = bindings.get(first, module + "." + first) + (dot + rest if dot else "")
        if qualified in seen or qualified not in constants:
            break
        seen.add(qualified)
        declared = constants[qualified]
        module = qualified.rsplit(".", 1)[0]
        bindings = bindings_by_module.get(module, bindings)
    if not isinstance(declared, (ast.List, ast.Tuple)):
        return []
    return [(item, bindings, module) for item in declared.elts
            if isinstance(item, ast.Call) and call_name(item, bindings) == "Depends"]


def scan_python_document(roots: List[Path]) -> ApiDocument:
    schemas: Dict[str, Schema] = {}
    endpoints: List[Endpoint] = []
    units = []
    for path in python_files(roots):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module = module_name(path, roots)
        units.append((path, tree, module))
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and any(source_text(base).endswith("BaseModel") for base in node.bases):
                fields = [Field(item.target.id, source_text(item.annotation)) for item in node.body
                          if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)]
                qualified = module + "." + node.name
                schema_id = "python:" + qualified
                schemas[schema_id] = Schema(schema_id, node.name, qualified, "", fields)
    by_name = {}
    for schema in schemas.values():
        by_name.setdefault(schema.name, []).append(schema)
    constants = {module + "." + name: value for _, tree, module in units
                 for name, value in module_constants(tree).items()}
    bindings_by_module = {module: import_bindings(tree, module, path.name == "__init__.py")
                          for path, tree, module in units}
    prefixes = route_prefixes(units, constants, bindings_by_module)
    instances = set()
    functions = {}
    for path, tree, module in units:
        bindings = import_bindings(tree, module, path.name == "__init__.py")
        resolve = lambda value, statement: constant_value(
            value, module, bindings, constants_before(tree, module, constants, statement), bindings_by_module)
        routers, apps = fastapi_instances(tree, bindings, resolve)
        instances.update(module + "." + name for name in set(routers) | apps)
        functions.update((module + "." + node.name, (node, bindings, module)) for node in tree.body
                         if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)))
    for path, tree, module in units:
        bindings = import_bindings(tree, module, path.name == "__init__.py")
        resolve_at = lambda value, statement: constant_value(
            value, module, bindings, constants_before(tree, module, constants, statement), bindings_by_module)
        routers, apps = fastapi_instances(tree, bindings, resolve_at)
        for schema in schemas.values():
            if schema.qualified_name.startswith(module + "."):
                for field in schema.fields:
                    field.schema_id = resolve_schema_id(field.type_name, module, bindings, by_name, schemas)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            resolve = lambda value: resolve_at(value, node)
            mappings = []
            for decorator in node.decorator_list:
                value = decorator_mapping(decorator, resolve)
                if value:
                    mappings.append(value)
                elif isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute) \
                        and decorator.func.attr in set(HTTP_METHODS) | {"api_route"} \
                        and isinstance(decorator.func.value, ast.Name):
                    owner = source_text(decorator.func.value)
                    if resolve_reference(owner, module, bindings) in instances:
                        print(f"Warning: unresolved FastAPI mapping at {path}:{node.lineno}", file=sys.stderr)
            for methods, route, owner, decorator in mappings:
                owner_id = resolve_reference(owner, module, bindings)
                if owner_id not in instances:
                    continue
                route_bases = prefixes.get(owner_id, [(routers.get(owner, ""), [])])
                for prefix, inherited in route_bases:
                    parameters, body_fields = [], []
                    embed_body = False

                    def collect(function, function_bindings, function_module, seen):
                        nonlocal embed_body
                        arguments = function.args.args + function.args.kwonlyargs
                        defaults = ([None] * (len(function.args.args) - len(function.args.defaults))
                                    + list(function.args.defaults) + list(function.args.kw_defaults))
                        for parameter, default in zip(arguments, defaults):
                            annotation, annotated_marker = annotation_parameter(parameter.annotation, function_bindings)
                            marker = default if isinstance(default, ast.Call) and call_name(default, function_bindings) in PARAMETER_MARKERS | {"Depends"} else annotated_marker
                            if parameter.arg == "self":
                                continue
                            if isinstance(marker, ast.Call) and call_name(marker, function_bindings) == "Depends":
                                collect_dependency(marker, function_bindings, function_module, seen)
                                continue
                            annotation_name = source_text(annotation)
                            resolved_annotation = function_bindings.get(annotation_name, annotation_name)
                            if resolved_annotation in {"fastapi.Request", "starlette.requests.Request", "fastapi.Response",
                                                       "starlette.responses.Response", "fastapi.BackgroundTasks"}:
                                continue
                            field = Field(parameter.arg, annotation_name, required=is_required(default, function_bindings))
                            field.example = literal_default(default, function_bindings)
                            field.schema_id = resolve_schema_id(field.type_name, function_module, function_bindings, by_name, schemas)
                            location = parameter_location(marker, function_bindings)
                            if isinstance(marker, ast.Call):
                                alias = next((keyword.value.value for keyword in marker.keywords
                                              if keyword.arg == "alias" and isinstance(keyword.value, ast.Constant)), None)
                                field.wire_name = str(alias) if alias is not None else ""
                            if location == "body" or field.schema_id and location != "query":
                                body_fields.append(field)
                            elif field.schema_id and field.type_name not in SCALARS:
                                body_fields.append(field)
                            else:
                                field.location = location
                                if field.location == "query" and re.search(r"\{" + re.escape(field.name) + r"(?::[^}]+)?\}", route):
                                    field.location = "path"
                                if field.location == "path":
                                    field.required = True
                                if field.location == "header" and not field.wire_name:
                                    convert = next((keyword.value.value for keyword in marker.keywords
                                                    if keyword.arg == "convert_underscores" and isinstance(keyword.value, ast.Constant)), True)
                                    field.wire_name = field.name.replace("_", "-") if convert else field.name
                                parameters.append(field)
                            if location == "body" and isinstance(marker, ast.Call):
                                embed_body = embed_body or any(keyword.arg == "embed" and isinstance(keyword.value, ast.Constant)
                                                               and keyword.value.value is True for keyword in marker.keywords)

                    def collect_dependency(marker, dependency_bindings, dependency_module, seen):
                        dependency = marker.args[0] if marker.args else next(
                            (item.value for item in marker.keywords if item.arg == "dependency"), None)
                        name = source_text(dependency)
                        dependency_id = resolve_reference(name, dependency_module, dependency_bindings)
                        if dependency_id in functions and dependency_id not in seen:
                            target, target_bindings, target_module = functions[dependency_id]
                            collect(target, target_bindings, target_module, seen | {dependency_id})

                    collect(node, bindings, module, {module + "." + node.name})
                    for marker, dependency_bindings, dependency_module in dependency_calls(
                            decorator, bindings, module, constants_before(tree, module, constants, node), bindings_by_module):
                        collect_dependency(marker, dependency_bindings, dependency_module, {module + "." + node.name})
                    for marker, dependency_bindings, dependency_module in inherited:
                        collect_dependency(marker, dependency_bindings, dependency_module, {module + "." + node.name})
                    parameters = list({(field.location, field.wire_name or field.name): field
                                       for field in parameters}.values())
                    response_node = next((keyword.value for keyword in decorator.keywords if keyword.arg == "response_model"), node.returns)
                    response_type = source_text(response_node)
                    response_schema_id = resolve_schema_id(response_type, module, bindings, by_name, schemas)
                    request_body = body_fields[0] if len(body_fields) == 1 and not embed_body else None
                    if body_fields and request_body is None:
                        schema_name = node.name + "RequestBody"
                        schema_id = "python:" + module + "." + schema_name + ":" + str(node.lineno)
                        schemas[schema_id] = Schema(schema_id, schema_name, module + "." + schema_name, "", body_fields)
                        request_body = Field("request", schema_name, required=any(field.required for field in body_fields),
                                             schema_id=schema_id)
                    content_type = ("application/json" if request_body else
                                    "multipart/form-data" if any(field.location == "file" for field in parameters) else
                                    "application/x-www-form-urlencoded" if any(field.location == "form" for field in parameters) else "")
                    for method in methods:
                        endpoints.append(Endpoint(node.name, ast.get_docstring(node) or node.name, method, join_path(prefix, route), parameters,
                                                      request_body, response_type, str(path) + ":" + str(node.lineno),
                                                      content_type, response_schema_id))
    return ApiDocument(1, "python", "fastapi", sorted(endpoints, key=lambda item: (item.path, item.method, item.name)), schemas).normalized()
