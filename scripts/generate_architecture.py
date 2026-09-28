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
        if name == "render":
            command.add_argument("--archify-cli", type=Path, help="require this official Archify CLI")
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
    result = {"valid": True, "artifacts": [str(output / filename) for filename in artifacts],
              "archifyRendered": False}
    target = output / "architecture.archify.html"
    target.unlink(missing_ok=True)
    archify = shutil.which(str(args.archify_cli)) if args.archify_cli else shutil.which("archify")
    if archify:
        process = subprocess.run([archify, "deliver", "architecture", str(output / "architecture.archify.json"),
                                  str(target), "--quality", "showcase", "--json"], text=True, capture_output=True)
        try:
            receipt = json.loads(process.stdout)
        except ValueError:
            receipt = None
        validation = receipt.get("validation", {}) if isinstance(receipt, dict) else {}
        if not isinstance(validation, dict):
            validation = {}
        check_count = validation.get("checkCount")
        accepted = (process.returncode == 0 and target.is_file() and isinstance(receipt, dict) and
                    receipt.get("ok") is True and receipt.get("command") == "deliver" and
                    validation.get("compositionProfile") == "showcase" and
                    validation.get("compositionStatus") == "pass" and
                    isinstance(check_count, int) and check_count > 0 and
                    validation.get("checksPassed") == check_count and
                    validation.get("errors") == 0 and validation.get("warnings") == 0)
        if accepted:
            result["artifacts"].append(str(target))
            result["archifyRendered"] = True
            result["archifyReceipt"] = receipt
        else:
            target.unlink(missing_ok=True)
            detail = process.stderr.strip() or (receipt.get("error") if isinstance(receipt, dict) else "")
            result["warnings"] = ["official Archify delivery failed: " + (detail or "invalid delivery receipt or missing HTML")]
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1
    else:
        result["warnings"] = ["Archify CLI is unavailable; schema-v1 JSON is ready for the official renderer"]
        if args.archify_cli:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
