#!/usr/bin/env python3
"""Build context, validate source-anchored architecture IR, and render diagrams."""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from architecture_ir import build_context, validate_architecture
from architecture_renderers import render_archify, render_drawio, render_mermaid, render_plantuml


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("context", "validate", "render"):
        command = commands.add_parser(name)
        command.add_argument("--source", type=Path, required=True, help="repository root")
        if name != "context":
            command.add_argument("--ir", type=Path, required=True)
        if name != "validate":
            command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.source.resolve()
    if not root.is_dir():
        parser.error(f"source directory does not exist: {root}")

    if args.command == "context":
        context = build_context(root)
        _write(args.output.resolve(), json.dumps(context, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"context": str(args.output.resolve()), "stats": context["stats"], "warnings": context["warnings"]}, ensure_ascii=False))
        return 0

    try:
        ir = json.loads(args.ir.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(json.dumps({"valid": False, "problems": [f"IR is unreadable: {error}"]}, ensure_ascii=False))
        return 1
    problems = validate_architecture(ir, root)
    if problems:
        print(json.dumps({"valid": False, "problems": problems}, ensure_ascii=False, indent=2))
        return 1
    if args.command == "validate":
        print(json.dumps({"valid": True, "domains": len(ir["domains"])}, ensure_ascii=False))
        return 0

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "architecture.mmd": render_mermaid(ir),
        "architecture.puml": render_plantuml(ir),
        "architecture.drawio": render_drawio(ir),
        "architecture.archify.json": json.dumps(render_archify(ir), ensure_ascii=False, indent=2) + "\n",
        "architecture.ir.json": json.dumps(ir, ensure_ascii=False, indent=2) + "\n",
    }
    for filename, content in artifacts.items():
        _write(output / filename, content)
    result = {"valid": True, "artifacts": [str(output / filename) for filename in artifacts]}
    archify = shutil.which("archify")
    if archify:
        target = output / "architecture.archify.html"
        process = subprocess.run([archify, "render", "architecture", str(output / "architecture.archify.json"), str(target)], text=True, capture_output=True)
        if process.returncode == 0:
            result["artifacts"].append(str(target))
        else:
            result["warnings"] = ["official Archify renderer rejected the adapter output: " + process.stderr.strip()]
    else:
        result["warnings"] = ["Archify CLI is unavailable; schema-v1 JSON is ready for the official renderer"]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
