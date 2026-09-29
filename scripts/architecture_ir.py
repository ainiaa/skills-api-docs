"""Source-anchored architecture IR and complete repository context."""

import json
import os
import re
import subprocess
from pathlib import Path

from discovery import CLASS_KINDS, select_engine
from tree_sitter_engine import extract_symbols, load_parsers, walk_source_files


SOURCE_SUFFIXES = {".java", ".kt", ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".php", ".sql", ".xml", ".yml", ".yaml", ".properties"}
SKIP_DIRS = {".git", ".codegraph", ".ua", ".understand-anything", "node_modules", "build", "dist", "target", ".venv", "venv", "__pycache__"}
PROVENANCE = {"EXTRACTED", "INFERRED", "AMBIGUOUS"}
IDENTIFIER = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
DECLARATION = re.compile(r"\b(class|interface|enum|record|struct|trait|protocol|def|function|func)\s+([A-Za-z_$][\w$]*)")
GO_DECLARATION = re.compile(r"\btype\s+([A-Za-z_]\w*)\s+(struct|interface)\b")
ROUTE = re.compile(r"(?:@(?:app|router)\.(?:get|post|put|delete|patch)|\b(?:app|router)\.(?:get|post|put|delete|patch))\s*\(\s*['\"]([^'\"]+)['\"]")
JAVA_MAPPING = re.compile(r"(?m)^[ \t]*@(?:HttpApi)?(?:Request|Get|Post|Put|Delete|Patch)Mapping\s*\(([^)]*)\)", re.DOTALL)
JAVA_ROUTE_NAMED = re.compile(r"\b(?:value|path)\s*=\s*(['\"])(.*?)\1", re.DOTALL)
JAVA_ROUTE_DIRECT = re.compile(r"\s*(['\"])(.*?)\1", re.DOTALL)
TABLE = re.compile(r"(?:\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?|@TableName\s*\(\s*['\"])([A-Za-z_][\w.]*)", re.IGNORECASE)


def _head(root):
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def _project_changes(root, base=None):
    """Return project paths changed since base, including uncommitted files."""
    commands = []
    if base:
        commands.append(["diff", "--name-only", "-z", base, "HEAD", "--", "."])
    commands.extend((["diff", "--cached", "--name-only", "-z", "--", "."],
                     ["diff", "--name-only", "-z", "--", "."],
                     ["ls-files", "--others", "--exclude-standard", "-z", "--", "."]))
    changed = set()
    for arguments in commands:
        result = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True)
        if result.returncode:
            return None
        changed.update(path.decode("utf-8", errors="replace") for path in result.stdout.split(b"\0") if path)
    return {path for path in changed if not any(part in SKIP_DIRS for part in Path(path).parts)}


def _graph_status(root, graph_hash):
    if not graph_hash:
        return {"fresh": False, "reason": "missing source revision"}
    resolved = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "--end-of-options",
                               f"{graph_hash}^{{commit}}"], capture_output=True, text=True)
    if resolved.returncode:
        return {"fresh": False, "reason": "unresolvable source revision"}
    changes = _project_changes(root, resolved.stdout.strip())
    if changes is None:
        return {"fresh": False, "reason": "cannot inspect source changes"}
    if changes:
        return {"fresh": False, "reason": "source changed", "changedFiles": sorted(changes)}
    return {"fresh": True, "reason": "source unchanged"}


def _fresh_graph_nodes(root):
    ua = root / ".ua"
    if not ua.is_dir():
        ua = root / ".understand-anything"
    path = ua / "knowledge-graph.json"
    if not path.is_file():
        return None
    try:
        graph = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not _graph_status(root, graph.get("project", {}).get("gitCommitHash"))["fresh"]:
        return None
    return graph.get("nodes", [])


def build_context(root):
    """Inventory all relevant source files; never silently cap the list."""
    root = Path(root).resolve()
    files = [path.relative_to(root).as_posix() for path in walk_source_files([root], sorted(SOURCE_SUFFIXES))
             if path.is_file() and not any(part in SKIP_DIRS for part in path.relative_to(root).parts)]

    context = {"version": 1, "project": root.name, "gitCommitHash": _head(root), "files": sorted(files),
               "packages": sorted({str(Path(name).parent).replace("\\", "/") for name in files}),
               "symbols": [], "routes": [], "configKeys": [], "tables": []}
    parsers = load_parsers()
    for relative in context["files"]:
        path = root / relative
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        if path.suffix in {".java", ".kt"}:
            source_text = "\n".join(lines)
            for match in JAVA_MAPPING.finditer(source_text):
                route = JAVA_ROUTE_NAMED.search(match[1]) or JAVA_ROUTE_DIRECT.match(match[1])
                if route:
                    context["routes"].append({"value": route[2], "path": relative,
                                              "line": source_text.count("\n", 0, match.start()) + 1})
        parser = parsers.get(path.suffix)
        if parser:
            try:
                source = path.read_bytes()
                node = parser["parser"].parse(source).root_node
                for kind, name, line_number, package in extract_symbols(node, source, parser):
                    context["symbols"].append({"name": name, "kind": kind, "path": relative,
                                               "line": line_number, "package": package, "source": "tree-sitter"})
            except (OSError, UnicodeError, ValueError):
                parser = None
        yaml_keys = []
        for number, line in enumerate(lines, 1):
            stripped = line.lstrip()
            if stripped.startswith(("//", "#", "*", "--")):
                continue
            if not parser:
                for match in DECLARATION.finditer(line):
                    context["symbols"].append({"name": match[2], "kind": match[1], "path": relative, "line": number, "source": "line-scan"})
                for match in GO_DECLARATION.finditer(line):
                    context["symbols"].append({"name": match[1], "kind": match[2], "path": relative, "line": number, "source": "line-scan"})
            for match in ROUTE.finditer(line):
                context["routes"].append({"value": match[1], "path": relative, "line": number})
            for match in TABLE.finditer(line):
                context["tables"].append({"name": match[1], "path": relative, "line": number})
            if path.suffix == ".properties":
                match = re.match(r"\s*([\w.-]+)\s*[=:]", line)
                if match:
                    context["configKeys"].append({"key": match[1], "path": relative, "line": number})
            elif path.suffix in {".yml", ".yaml"}:
                match = re.match(r"^(\s*)([\w.-]+)\s*:", line)
                if match:
                    level = len(match[1].expandtabs(2)) // 2
                    yaml_keys = yaml_keys[:level] + [match[2]]
                    context["configKeys"].append({"key": ".".join(yaml_keys), "path": relative, "line": number})
    ua = root / ".ua"
    if not ua.is_dir() and (root / ".understand-anything").is_dir():
        ua = root / ".understand-anything"
    warnings = []
    if context["gitCommitHash"] and _project_changes(root):
        warnings.append("working tree differs from HEAD; cached graph or domain graph may be stale")
    context["graphStatus"] = {}
    for filename, field in (("knowledge-graph.json", "knowledgeGraph"), ("domain-graph.json", "domainGraph")):
        path = ua / filename
        if not path.is_file():
            continue
        try:
            graph = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            warnings.append(f"{filename}: {error}")
            continue
        graph_hash = graph.get("project", {}).get("gitCommitHash", "")
        status = _graph_status(root, graph_hash)
        context["graphStatus"][field] = status
        if not status["fresh"]:
            warnings.append(f"{filename} is stale or unverified: {status['reason']}")
        context[field] = graph
    context["stats"] = {"files": len(files), "symbols": len(context["symbols"]), "routes": len(context["routes"]),
                        "configKeys": len(context["configKeys"]), "tables": len(context["tables"]),
                        "graphNodes": len(context.get("knowledgeGraph", {}).get("nodes", [])), "graphEdges": len(context.get("knowledgeGraph", {}).get("edges", []))}
    context["warnings"] = warnings
    return context


def _check_evidence(value, root, label, problems):
    if not isinstance(value, list) or not value:
        problems.append(f"{label}: evidence must be a non-empty list")
        return []
    verified = []
    for index, item in enumerate(value):
        target = f"{label}.evidence[{index}]"
        if not isinstance(item, dict):
            problems.append(f"{target}: expected object")
            continue
        relative, line, quote = item.get("path"), item.get("line"), item.get("quote")
        if not isinstance(relative, str) or not relative or not isinstance(line, int) or isinstance(line, bool) or line < 1 or not isinstance(quote, str) or not quote.strip():
            problems.append(f"{target}: path, positive line, and non-empty quote are required")
            continue
        try:
            path = (root / relative).resolve()
            valid_path = os.path.commonpath((str(root), str(path))) == str(root) and path.is_file()
        except (OSError, ValueError):
            valid_path = False
        if not valid_path:
            problems.append(f"{target}: path is outside source root or missing: {relative}")
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            problems.append(f"{target}: source is unreadable: {relative}")
            continue
        if line > len(lines) or quote not in lines[line - 1]:
            problems.append(f"{target}: quote does not occur on source line {line}")
            continue
        source_line = lines[line - 1].lstrip()
        if source_line.startswith(("//", "#", "*", "--")):
            problems.append(f"{target}: comment-only line is not source evidence")
            continue
        verified.append(lines[line - 1])
    return verified


def _class_declared(lines, name):
    return any(any(match[1] in {"class", "interface", "enum", "record", "struct", "trait", "protocol"} and match[2] == name
                   for match in DECLARATION.finditer(line)) or
               any(match[1] == name for match in GO_DECLARATION.finditer(line)) for line in lines)


def _xml_safe(value):
    return all(char in "\t\n\r" or 0x20 <= ord(char) <= 0xD7FF or
               0xE000 <= ord(char) <= 0xFFFD or 0x10000 <= ord(char) <= 0x10FFFF
               for char in value)


def _claim(item, field, root, label, problems, literal=False, declaration=False):
    if not isinstance(item, dict) or not isinstance(item.get(field), str) or not item[field].strip():
        problems.append(f"{label}: non-empty {field} is required")
        return
    if not _xml_safe(item[field]):
        problems.append(f"{label}: {field} contains characters unsupported by XML")
    status = item.get("provenance")
    if not isinstance(status, str) or status not in PROVENANCE:
        problems.append(f"{label}: provenance must be EXTRACTED, INFERRED, or AMBIGUOUS")
    lines = _check_evidence(item.get("evidence"), root, label, problems)
    if status == "EXTRACTED" and not literal and lines and not any(item[field] in line for line in lines):
        problems.append(f"{label}: EXTRACTED {item[field]} is not literal on cited source lines")
    if literal and lines and not any(re.search(r"(?<![\w])" + re.escape(item[field]) + r"(?![\w])", line) for line in lines):
        problems.append(f"{label}: {item[field]} is absent from cited source lines")
    if declaration and lines and not _class_declared(lines, item[field]):
        problems.append(f"{label}: {item[field]} has no class or interface declaration on cited lines")
    if literal and status != "EXTRACTED":
        problems.append(f"{label}: literal source fact requires EXTRACTED provenance")


def validate_architecture(ir, root):
    """Validate shape and source existence; semantic truth remains reviewable inference."""
    root = Path(root).resolve()
    problems = []
    if not isinstance(ir, dict) or ir.get("version") != 1:
        return ["IR version must be 1"]
    if not isinstance(ir.get("summary"), str) or not ir["summary"].strip():
        problems.append("summary must be non-empty")
    elif not _xml_safe(ir["summary"]):
        problems.append("summary contains characters unsupported by XML")
    domains = ir.get("domains")
    if not isinstance(domains, list) or not domains:
        return problems + ["domains must be a non-empty list"]
    graph_nodes = _fresh_graph_nodes(root)
    discovery = select_engine([root]) if graph_nodes is None and (root / ".codegraph").is_dir() else None
    ids = set()
    for index, domain in enumerate(domains):
        label = f"domains[{index}]"
        if not isinstance(domain, dict):
            problems.append(f"{label}: expected object")
            continue
        domain_id = domain.get("id")
        if not isinstance(domain_id, str) or not IDENTIFIER.fullmatch(domain_id):
            problems.append(f"{label}: id must be a stable identifier")
        elif domain_id in ids:
            problems.append(f"{label}: duplicate domain id {domain_id}")
        else:
            ids.add(domain_id)
        for key in ("name", "responsibility"):
            if not isinstance(domain.get(key), str) or not domain[key].strip():
                problems.append(f"{label}: {key} must be non-empty")
            elif not _xml_safe(domain[key]):
                problems.append(f"{label}: {key} contains characters unsupported by XML")
        if not isinstance(domain.get("provenance"), str) or domain["provenance"] not in {"INFERRED", "AMBIGUOUS"}:
            problems.append(f"{label}: domain provenance must be INFERRED or AMBIGUOUS")
        _check_evidence(domain.get("evidence"), root, label, problems)
        for key, field, literal in (("capabilities", "text", False), ("keyClasses", "name", True), ("tables", "name", True)):
            values = domain.get(key)
            if not isinstance(values, list) or (key == "capabilities" and not values):
                problems.append(f"{label}.{key}: expected {'non-empty ' if key == 'capabilities' else ''}list")
                continue
            for position, item in enumerate(values):
                _claim(item, field, root, f"{label}.{key}[{position}]", problems, literal, key == "keyClasses")
                if graph_nodes is not None and isinstance(item, dict) and isinstance(item.get(field), str) and key in {"keyClasses", "tables"}:
                    node_type = "class" if key == "keyClasses" else "table"
                    evidence_paths = {e.get("path") for e in item.get("evidence", []) if isinstance(e, dict)}
                    matched = any(node.get("type") == node_type and node.get("name") == item[field] and
                                  (not node.get("filePath") or node.get("filePath") in evidence_paths)
                                  for node in graph_nodes if isinstance(node, dict))
                    if not matched:
                        problems.append(f"{label}.{key}[{position}]: {item[field]} is absent from fresh knowledge graph")
                elif discovery is not None and key == "keyClasses" and isinstance(item, dict) and isinstance(item.get("name"), str):
                    locations = discovery.locate(item["name"], CLASS_KINDS)
                    evidence_locations = {(root / evidence["path"]).resolve() for evidence in item.get("evidence", [])
                                          if isinstance(evidence, dict) and isinstance(evidence.get("path"), str)}
                    if not any(location.path in evidence_locations for location in locations):
                        problems.append(f"{label}.{key}[{position}]: {item['name']} is absent from discovery graph at cited path")
    for key in ("externalSystems", "relations"):
        values = ir.get(key)
        if not isinstance(values, list):
            problems.append(f"{key}: expected list")
            continue
        for index, item in enumerate(values):
            label = f"{key}[{index}]"
            if not isinstance(item, dict):
                problems.append(f"{label}: expected object")
                continue
            if key == "externalSystems":
                _claim(item, "name", root, label, problems)
                if "kind" in item and (not isinstance(item["kind"], str) or not item["kind"].strip() or not _xml_safe(item["kind"])):
                    problems.append(f"{label}: kind must be non-empty XML-safe text")
                if not isinstance(item.get("domain"), str) or item["domain"] not in ids:
                    problems.append(f"{label}: domain references missing domain {item.get('domain')}")
                via = item.get("via")
                if not isinstance(via, list) or not via or any(not isinstance(name, str) or not name.strip() for name in via):
                    problems.append(f"{label}: via must contain client names")
                else:
                    cited_lines = _check_evidence(item.get("evidence"), root, label, [])
                    for name in via:
                        if not _class_declared(cited_lines, name):
                            problems.append(f"{label}: via {name} has no class or interface declaration on cited lines")
            else:
                _claim(item, "label", root, label, problems)
                if item.get("provenance") == "EXTRACTED":
                    problems.append(f"{label}: relation provenance must be INFERRED or AMBIGUOUS")
                for side in ("from", "to"):
                    if not isinstance(item.get(side), str) or item[side] not in ids:
                        problems.append(f"{label}: {side} references missing domain {item.get(side)}")
    return problems
