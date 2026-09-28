#!/usr/bin/env python3
"""Build context, validate source-anchored architecture IR, and render diagrams."""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from architecture_ir import build_context, validate_architecture
from architecture_renderers import render_archify, render_drawio, render_mermaid, render_plantuml


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _render_svg(kind, executable, source, target):
    """Ask the official renderer to export an SVG, then accept only a valid SVG file."""
    target.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as directory:
        temporary = Path(directory) / "diagram.svg"
        if kind == "mermaid":
            commands = [[executable, "-i", str(source), "-o", str(temporary)]]
        elif kind == "plantuml":
            commands = [[executable, "-checkonly", str(source)],
                        [executable, "-tsvg", "-o", directory, str(source)]]
            temporary = Path(directory) / (source.stem + ".svg")
        else:
            commands = [[executable, "--export", "--format", "svg", "--output", str(temporary), str(source)]]
        try:
            for command in commands:
                process = subprocess.run(command, text=True, capture_output=True, timeout=120)
                if process.returncode:
                    return process.stderr.strip() or process.stdout.strip() or f"exit code {process.returncode}"
            if ET.parse(temporary).getroot().tag != "{http://www.w3.org/2000/svg}svg":
                return "renderer did not produce an SVG document"
            temporary.replace(target)
        except (OSError, ET.ParseError, subprocess.TimeoutExpired) as error:
            return str(error)
    return None


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
            for kind in ("mermaid", "plantuml", "drawio"):
                command.add_argument(f"--{kind}-cli", type=Path, help=f"require this official {kind} CLI")
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
              "archifyRendered": False, "rendererChecks": {}}
    failures = []
    warnings = []
    for kind, input_name in (("mermaid", "architecture.mmd"),
                             ("plantuml", "architecture.puml"),
                             ("drawio", "architecture.drawio")):
        target_svg = output / f"architecture.{kind}.svg"
        target_svg.unlink(missing_ok=True)
        requested = getattr(args, f"{kind}_cli")
        executable = shutil.which(str(requested)) if requested else shutil.which(
            {"mermaid": "mmdc", "plantuml": "plantuml", "drawio": "drawio"}[kind])
        if not executable:
            result["rendererChecks"][kind] = "fail" if requested else "skipped"
            if requested:
                failures.append(f"{kind} CLI is unavailable: {requested}")
            else:
                warnings.append(f"{kind} CLI is unavailable; {input_name} was not engine-validated")
            continue
        error = _render_svg(kind, executable, output / input_name, target_svg)
        result["rendererChecks"][kind] = "fail" if error else "pass"
        if error:
            failures.append(f"official {kind} render failed: {error}")
        else:
            result["artifacts"].append(str(target_svg))
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
            failures.append("official Archify delivery failed: " + (detail or "invalid delivery receipt or missing HTML"))
    else:
        warnings.append("Archify CLI is unavailable; schema-v1 JSON is ready for the official renderer")
        if args.archify_cli:
            failures.append(f"Archify CLI is unavailable: {args.archify_cli}")
    if warnings:
        result["warnings"] = warnings
    if failures:
        result["problems"] = failures
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
