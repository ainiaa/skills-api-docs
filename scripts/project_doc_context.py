"""Extract a focused, source-located project-document context from a repository."""

import argparse
import json
from pathlib import Path

from architecture_ir import build_context


def _related_graph(graph, paths, terms):
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    selected = {node.get("id") for node in nodes if node.get("filePath") in paths
                or any(term in str(node.get(key, "")).casefold() for key in ("name", "summary") for term in terms)}
    for edge in edges:
        if edge.get("source") in selected or edge.get("target") in selected:
            selected.update((edge.get("source"), edge.get("target")))
    return ([node for node in nodes if node.get("id") in selected],
            [edge for edge in edges if edge.get("source") in selected and edge.get("target") in selected])


def focused_context(context, focus):
    terms = [item.casefold() for item in focus if item.strip()]
    paths = {path for path in context["files"] if any(term in path.casefold() for term in terms)}
    for field, key in (("symbols", "name"), ("routes", "value"), ("configKeys", "key"), ("tables", "name")):
        paths.update(item["path"] for item in context[field]
                     if any(term in str(item[key]).casefold() for term in terms))
    result = {"project": context["project"], "gitCommitHash": context["gitCommitHash"],
              "focus": focus, "totalFiles": len(context["files"]), "matchedFiles": sorted(paths),
              "needsBroaderSearch": not bool(paths), "warnings": list(context["warnings"])}
    for field in ("symbols", "routes", "configKeys", "tables"):
        result[field] = [item for item in context[field] if item["path"] in paths]
    for field, prefix in (("knowledgeGraph", "graph"), ("domainGraph", "domain")):
        status = context.get("graphStatus", {}).get(field, {})
        if status.get("fresh"):
            result[prefix + "Nodes"], result[prefix + "Edges"] = _related_graph(context[field], paths, terms)
            if field == "knowledgeGraph":
                selected = {node.get("id") for node in result["graphNodes"]}
                result["graphLayers"] = [layer for layer in context[field].get("layers", [])
                                         if selected.intersection(layer.get("nodeIds", []))]
                result["graphTour"] = [step for step in context[field].get("tour", [])
                                       if selected.intersection(step.get("nodeIds", []))]
        else:
            result[prefix + "Nodes"], result[prefix + "Edges"] = [], []
            if field == "knowledgeGraph":
                result["graphLayers"], result["graphTour"] = [], []
            if field in context:
                result["warnings"].append(f"{field} stale; omitted from focused context")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--focus", action="append", required=True, help="file, symbol, route, or business term; repeat as needed")
    parser.add_argument("--output", type=Path, help="write JSON here instead of stdout")
    args = parser.parse_args()
    if not args.source.is_dir():
        parser.error("--source must be an existing directory")
    result = focused_context(build_context(args.source), args.focus)
    content = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
        print(json.dumps({"output": str(args.output), "matchedFiles": len(result["matchedFiles"]),
                          "warnings": result["warnings"]}, ensure_ascii=False))
    else:
        print(content, end="")


if __name__ == "__main__":
    main()
