"""Read structured CodeGraph evidence through its public CLI."""

import json
import shutil
import subprocess
from pathlib import Path


def _call(run, argv):
    result = run(argv, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise ValueError(result.stderr.strip() or f"CodeGraph exited {result.returncode}")
    return json.loads(result.stdout)


def load_codegraph(root, focus=(), executable=None, run=subprocess.run):
    """Return fresh class/route nodes and focused callees, or a warning and no graph."""
    root = Path(root).resolve()
    if not (root / ".codegraph").is_dir():
        return None, []
    binary = executable or shutil.which("codegraph")
    if not binary:
        return None, ["CodeGraph index exists but codegraph CLI is unavailable"]
    try:
        status = _call(run, [binary, "status", "--json", str(root)])
        if not isinstance(status, dict):
            raise ValueError("CodeGraph status did not return an object")
        pending = status.get("pendingChanges") or {}
        index = status.get("index") or {}
        kinds = status.get("nodesByKind") or {}
        if not all(isinstance(value, dict) for value in (pending, index, kinds)):
            raise ValueError("CodeGraph status has invalid fields")
        if (not status.get("initialized") or status.get("worktreeMismatch") or
                index.get("reindexRecommended") or
                any(pending.get(key, 0) for key in ("added", "modified", "removed"))):
            return None, ["CodeGraph index is stale; verify current source before diagramming"]
        graph = {"status": status, "classes": [], "routes": [], "calls": {}}
        for kind, field in (("class", "classes"), ("route", "routes")):
            count = kinds.get(kind, 0)
            if not isinstance(count, int) or count < 0:
                raise ValueError(f"CodeGraph {kind} count is invalid")
            limit = max(100000, count + 1)
            rows = _call(run, [binary, "query", "", "--limit", str(limit),
                               "--kind", kind, "--json", "-p", str(root)])
            if not isinstance(rows, list):
                raise ValueError(f"CodeGraph {kind} query did not return a list")
            if count and len(rows) < count:
                raise ValueError(f"CodeGraph {kind} query returned fewer nodes than status reports")
            for row in rows:
                node = row.get("node") if isinstance(row, dict) else None
                if not isinstance(node, dict) or node.get("kind") != kind:
                    continue
                relative = node.get("filePath")
                if not isinstance(relative, str) or not relative:
                    continue
                candidate = (root / relative).resolve()
                if not candidate.is_relative_to(root) or not candidate.is_file():
                    continue
                graph[field].append({key: node[key] for key in
                                     ("id", "kind", "name", "qualifiedName", "filePath", "startLine")
                                     if key in node})
        for symbol in dict.fromkeys(focus):
            if not isinstance(symbol, str) or not symbol.strip():
                raise ValueError("CodeGraph focus must be a non-empty symbol")
            result = _call(run, [binary, "callees", symbol, "--json", "-p", str(root)])
            callees = result.get("callees") if isinstance(result, dict) else None
            if not isinstance(callees, list):
                raise ValueError(f"CodeGraph callees for {symbol} did not return a list")
            graph["calls"][symbol] = [item for item in callees if isinstance(item, dict)]
        return graph, []
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, json.JSONDecodeError) as error:
        return None, [f"CodeGraph evidence unavailable: {error}"]
