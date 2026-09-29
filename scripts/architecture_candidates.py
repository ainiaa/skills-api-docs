"""High-signal repository candidates for architecture overview coverage."""

import hashlib
import json
import re
from pathlib import Path

from architecture_ir import _check_evidence, build_context
from diagram_profiles import validate_view


SIGNALS = (
    ("entrypoint", re.compile(r"@(?:HttpApi)?(?:Request|Get|Post|Put|Delete|Patch)Mapping\b")),
    ("external_client", re.compile(r"@FeignClient\b|\b(?:RestTemplate|WebClient|OkHttpClient)\b")),
    ("cache", re.compile(r"\b(?:RedisTemplate|StringRedisTemplate|RedissonClient|RedisManager|ICacheManager|RLock)\b")),
    ("database", re.compile(r"@Mapper\b|@MapperScan\b|@TableName\b|"
                            r"\b(?:SqlSessionFactory|JdbcTemplate)\b|\bextends\s+BaseMapper\b")),
    ("messaging", re.compile(r"\b(?:KafkaTemplate|RabbitTemplate|RocketMQTemplate)\b")),
    ("scheduler", re.compile(r"@Scheduled\b|@XxlJob\b")),
)


def _scoped(path, prefixes):
    if ("/src/test/" in path or path.startswith("src/test/") or
            any(part.endswith("-test") for part in Path(path).parts)):
        return False
    return not prefixes or any(path == prefix or path.startswith(prefix + "/") for prefix in prefixes)


def _prefixes(values):
    prefixes = sorted(set(values or []))
    for value in prefixes:
        path = Path(value)
        if not value or path.is_absolute() or ".." in path.parts or value.startswith("."):
            raise ValueError(f"invalid scope prefix: {value}")
    return prefixes


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":")).encode("utf-8")).hexdigest()


def discover_candidates(root, scope_paths=()):
    """Scan source for review candidates, not inferred architecture facts."""
    root = Path(root).resolve()
    prefixes = _prefixes(scope_paths)
    context = build_context(root)
    files = [name for name in context["files"] if _scoped(name, prefixes)]
    if prefixes and not files:
        raise ValueError("scope prefixes matched no source files")
    source_hash = hashlib.sha256()
    found = {}

    def add(kind, path, line, quote):
        parts = Path(path).parts
        if kind == "cache" and "config" not in parts:
            kind = "cache_usage"
        if kind == "external_client" and parts[0].endswith("-client"):
            kind = "client_contract"
        key = (kind, path)
        if key not in found:
            found[key] = {"id": kind + "_" + _fingerprint(key)[:12], "kind": kind,
                          "name": ({"entrypoint": "HTTP entrypoints · ", "database": "Database access · ",
                                    "scheduler": "Scheduled jobs · ",
                                    "client_contract": "Published client contracts · "}.get(kind, "") + Path(path).stem),
                          "evidence": {"path": path, "line": line, "quote": quote.strip()},
                          "members": []}
        member = {"path": path, "line": line}
        if member not in found[key]["members"]:
            found[key]["members"].append(member)

    for route in context["routes"]:
        if _scoped(route["path"], prefixes):
            path = root / route["path"]
            try:
                text = path.read_text(encoding="utf-8")
                if "@FeignClient" in text:
                    continue
                quote = text.splitlines()[route["line"] - 1]
            except (OSError, UnicodeError, IndexError):
                continue
            add("entrypoint", route["path"], route["line"], quote)
    for relative in files:
        path = root / relative
        try:
            data = path.read_bytes()
            lines = data.decode("utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        source_hash.update(relative.encode("utf-8") + b"\0" + data + b"\0")
        mapstruct = any("org.mapstruct." in line for line in lines)
        feign_client = any("@FeignClient" in line for line in lines)
        for number, line in enumerate(lines, 1):
            if line.lstrip().startswith(("//", "#", "*", "--", "import ")):
                continue
            for kind, pattern in SIGNALS:
                if kind == "entrypoint" and feign_client:
                    continue
                if kind == "database" and mapstruct:
                    continue
                if kind == "external_client" and "/config/" in relative:
                    continue
                if pattern.search(line):
                    add(kind, relative, number, line)
    candidates = sorted(found.values(), key=lambda item: (item["kind"], item["evidence"]["path"]))
    return {"version": 1, "project": root.name, "scopePaths": prefixes,
            "sourceFingerprint": source_hash.hexdigest(), "candidates": candidates}


def _detail_path(base, filename, label, problems):
    if not isinstance(filename, str) or not filename.strip():
        problems.append(f"{label}: detailView is required")
        return None
    path = (base / filename).resolve()
    if not path.is_relative_to(base):
        problems.append(f"{label}: referenced file must stay beside the overview IR")
        return None
    return path


def validate_candidate_coverage(ir, root, ir_path):
    """Verify fresh generated candidates have explicit, source-linked dispositions."""
    coverage = ir.get("coverage")
    if ir.get("profile") != "architecture-landscape" or not isinstance(coverage, dict):
        return "not_checked", [], []
    inventory_name = coverage.get("inventoryFile")
    if inventory_name is None:
        return "not_checked", [], []
    problems = []
    base = Path(ir_path).resolve().parent
    inventory_path = _detail_path(base, inventory_name, "coverage.inventoryFile", problems)
    if inventory_path is None:
        return "fail", problems, []
    try:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        return "fail", [f"coverage inventory is unreadable: {error}"], []
    if (not isinstance(inventory, dict) or inventory.get("version") != 1 or
            not isinstance(inventory.get("scopePaths"), list) or
            any(not isinstance(value, str) for value in inventory["scopePaths"])):
        return "fail", ["coverage inventory has invalid shape"], []
    try:
        current = discover_candidates(root, inventory["scopePaths"])
    except ValueError as error:
        return "fail", [str(error)], []
    if inventory != current:
        return "fail", ["coverage inventory is stale; regenerate it from current source"], []
    if inventory["scopePaths"] != ir.get("scope", {}).get("sourcePaths", []):
        return "fail", ["coverage inventory scopePaths must match scope.sourcePaths"], []
    decisions = coverage.get("decisions")
    if not isinstance(decisions, list):
        return "fail", ["coverage.decisions must be a list"], []
    candidates = {item["id"]: item for item in inventory["candidates"]}
    manual = coverage.get("manualCandidates", [])
    if not isinstance(manual, list):
        return "fail", ["coverage.manualCandidates must be a list"], []
    for index, item in enumerate(manual):
        label = f"coverage.manualCandidates[{index}]"
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            problems.append(f"{label}: id is required")
            continue
        if item["id"] in candidates:
            problems.append(f"{label}: duplicate candidate id {item['id']}")
            continue
        if not isinstance(item.get("kind"), str) or not item["kind"]:
            problems.append(f"{label}: kind is required")
        if not _check_evidence([item.get("evidence")], Path(root).resolve(), label, problems):
            continue
        if isinstance(item.get("kind"), str) and item["kind"]:
            candidates[item["id"]] = {"id": item["id"], "kind": item["kind"],
                                      "evidence": item["evidence"]}
    detail_paths = {}
    seen = set()
    for index, decision in enumerate(decisions):
        label = f"coverage.decisions[{index}]"
        if not isinstance(decision, dict):
            problems.append(f"{label}: expected object")
            continue
        candidate_id = decision.get("candidateId")
        if not isinstance(candidate_id, str) or candidate_id not in candidates or candidate_id in seen:
            problems.append(f"{label}: unknown or duplicate candidateId {candidate_id}")
            continue
        seen.add(candidate_id)
        status = decision.get("status")
        if status == "excluded":
            if not isinstance(decision.get("reason"), str) or not decision["reason"].strip():
                problems.append(f"{label}: exclusion reason is required")
            continue
        if status not in {"overview", "detail"}:
            problems.append(f"{label}: status must be overview, detail, or excluded")
            continue
        view = ir
        if status == "detail":
            detail_path = _detail_path(base, decision.get("detailView"), label, problems)
            if detail_path is None:
                continue
            if detail_path == Path(ir_path).resolve():
                problems.append(f"{label}: detailView must differ from the overview IR")
                continue
            try:
                view = json.loads(detail_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError) as error:
                problems.append(f"{label}: detailView is unreadable: {error}")
                continue
            detail_problems = validate_view(view, root)
            if detail_problems:
                problems.append(f"{label}: detailView is invalid: {'; '.join(detail_problems)}")
                continue
            if isinstance(view.get("coverage"), dict) and view["coverage"].get("omitted"):
                problems.append(f"{label}: nested detail omissions are not supported; flatten the bundle")
                continue
            detail_paths[str(detail_path)] = detail_path
        target = None
        element_id = decision.get("element")
        relation = decision.get("relation")
        if candidates[candidate_id]["kind"].endswith("_usage") and not isinstance(relation, dict):
            problems.append(f"{label}: usage candidate requires a relation mapping")
            continue
        if isinstance(element_id, str) and element_id:
            target = next((item for item in view["elements"] if item["id"] == element_id), None)
            if target is None:
                problems.append(f"{label}: missing element {element_id}")
        elif isinstance(relation, dict) and all(isinstance(relation.get(key), str) for key in ("from", "to", "label")):
            target = next((item for item in view["relations"] if all(item.get(key) == relation[key]
                           for key in ("from", "to", "label"))), None)
            if target is None:
                problems.append(f"{label}: missing relation {relation}")
        else:
            problems.append(f"{label}: element or relation mapping is required")
        if target is not None:
            required = candidates[candidate_id].get("members") or [candidates[candidate_id]["evidence"]]
            claimed = {(e.get("path"), e.get("line")) for e in target.get("evidence", [])
                       if isinstance(e, dict)}
            missing = [(member["path"], member["line"]) for member in required
                       if (member["path"], member["line"]) not in claimed]
            if missing:
                problems.append(f"{label}: mapped claim lacks candidate source anchors {missing}")
    for missing in sorted(set(candidates) - seen):
        problems.append(f"coverage: unclassified candidate {missing}")
    return ("fail" if problems else "pass"), problems, list(detail_paths.values())
