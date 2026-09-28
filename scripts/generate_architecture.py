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
from codegraph_context import load_codegraph
from diagram_profiles import CAPABILITIES, render_view, validate_view

EXPORT_FORMATS = {
    "mermaid": ("svg", "png", "pdf"),
    "plantuml": ("svg", "png", "pdf"),
    "drawio": ("svg", "png", "jpg", "pdf"),
    "archify": ("svg", "png", "jpg", "webp", "pdf", "webm"),
}


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _check_diagram(kind, executable, source, svg_target=None):
    """Validate with the official engine; keep its SVG only when requested."""
    if svg_target:
        svg_target.unlink(missing_ok=True)
    if kind == "plantuml" and svg_target is None:
        try:
            process = subprocess.run([executable, "-checkonly", str(source)],
                                     text=True, capture_output=True, timeout=120)
            if process.returncode:
                return process.stderr.strip() or process.stdout.strip() or f"exit code {process.returncode}"
        except (OSError, subprocess.TimeoutExpired) as error:
            return str(error)
        return None
    with tempfile.TemporaryDirectory(dir=source.parent) as directory:
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
            if svg_target:
                temporary.replace(svg_target)
        except (OSError, ET.ParseError, subprocess.TimeoutExpired) as error:
            return str(error)
    return None


def _check_export(path, fmt):
    if fmt == "svg":
        try:
            return None if ET.parse(path).getroot().tag == "{http://www.w3.org/2000/svg}svg" else "invalid SVG root"
        except ET.ParseError as error:
            return str(error)
    size = path.stat().st_size
    with path.open("rb") as artifact:
        head = artifact.read(24)
        artifact.seek(max(0, size - 32))
        tail = artifact.read()
    if fmt == "png" and (size >= 24 and head.startswith(b"\x89PNG\r\n\x1a\n") and
                         head[12:16] == b"IHDR" and int.from_bytes(head[16:20], "big") > 0 and
                         int.from_bytes(head[20:24], "big") > 0):
        return None
    if fmt == "jpg" and size > 4 and head.startswith(b"\xff\xd8\xff") and tail.endswith(b"\xff\xd9"):
        return None
    if fmt == "pdf" and head.startswith(b"%PDF-") and b"%%EOF" in tail:
        return None
    if fmt == "webp" and size > 12 and head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return None
    if fmt == "webm" and size > 4 and head.startswith(b"\x1a\x45\xdf\xa3"):
        return None
    return f"renderer did not produce a valid {fmt.upper()} file"


def _render_export(kind, executable, source, target, fmt):
    """Render one official output into a temporary directory before publishing it."""
    target.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(dir=source.parent) as directory:
        temporary = Path(directory) / f"diagram.{fmt}"
        if kind == "mermaid":
            command = [executable, "-i", str(source), "-o", str(temporary)]
        elif kind == "plantuml":
            command = [executable, "--format", fmt, "--output-dir", directory, str(source)]
            temporary = Path(directory) / f"{source.stem}.{fmt}"
        else:
            command = [executable, "--export", "--format", fmt, "--output", str(temporary), str(source)]
        try:
            process = subprocess.run(command, text=True, capture_output=True, timeout=120)
            if process.returncode:
                return process.stderr.strip() or process.stdout.strip() or f"exit code {process.returncode}"
            error = _check_export(temporary, fmt)
            if error:
                return error
            temporary.replace(target)
        except (OSError, subprocess.TimeoutExpired) as error:
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
            command.add_argument("--format", action="append", choices=("mermaid", "plantuml", "drawio", "archify"),
                                 help="requested diagram format; repeat for multiple formats")
            command.add_argument("--svg-for", action="append", choices=("mermaid", "plantuml", "drawio"),
                                 help="also deliver SVG for this selected format; repeat if needed")
            command.add_argument("--export-for", action="append", metavar="ENGINE:FORMAT",
                                 help="repeat as needed: Mermaid/PlantUML svg,png,pdf; drawio svg,png,jpg,pdf; "
                                      "Archify svg,png,jpg,webp,webm,pdf")
            command.add_argument("--archify-cli", type=Path, help="require this official Archify CLI")
            for kind in ("mermaid", "plantuml", "drawio"):
                command.add_argument(f"--{kind}-cli", type=Path, help=f"require this official {kind} CLI")
        if name == "context":
            command.add_argument("--focus", action="append", default=[],
                                 help="CodeGraph symbol whose direct callees should be included; repeat as needed")
    args = parser.parse_args(argv)
    if args.command == "render":
        if not args.format:
            parser.error("render requires at least one --format")
        selected = list(dict.fromkeys(args.format))
        svg_for = list(dict.fromkeys(args.svg_for or []))
        if any(kind not in selected for kind in svg_for):
            parser.error("each --svg-for requires a matching --format")
        exports = {kind: set() for kind in EXPORT_FORMATS}
        for value in args.export_for or []:
            kind, separator, fmt = value.partition(":")
            if not separator or fmt not in EXPORT_FORMATS.get(kind, ()):
                parser.error(f"unsupported --export-for {value}; see --help for supported engine formats")
            if kind not in selected:
                parser.error(f"--export-for {value} requires --format {kind}")
            exports[kind].add(fmt)
        for kind in svg_for:
            exports[kind].add("svg")
        for kind in ("archify", "mermaid", "plantuml", "drawio"):
            if getattr(args, f"{kind}_cli") and kind not in selected:
                parser.error(f"--{kind}-cli requires --format {kind}")
    root = args.source.resolve()
    if not root.is_dir():
        parser.error(f"source directory does not exist: {root}")

    if args.command == "context":
        context = build_context(root)
        graph, graph_warnings = load_codegraph(root, focus=args.focus)
        if graph is not None:
            context["codeGraph"] = graph
            context["stats"]["codeGraphClasses"] = len(graph["classes"])
            context["stats"]["codeGraphRoutes"] = len(graph["routes"])
        context["warnings"].extend(graph_warnings)
        _write(args.output.resolve(), json.dumps(context, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"context": str(args.output.resolve()), "stats": context["stats"], "warnings": context["warnings"]}, ensure_ascii=False))
        return 0

    try:
        ir = json.loads(args.ir.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(json.dumps({"valid": False, "problems": [f"IR is unreadable: {error}"]}, ensure_ascii=False))
        return 1
    problems = validate_view(ir, root) if isinstance(ir, dict) and ir.get("version") == 2 else validate_architecture(ir, root)
    if problems:
        print(json.dumps({"valid": False, "problems": problems}, ensure_ascii=False, indent=2))
        return 1
    if args.command == "validate":
        summary = ({"profile": ir["profile"], "elements": len(ir["elements"])}
                   if ir["version"] == 2 else {"domains": len(ir["domains"])})
        print(json.dumps({"valid": True, **summary}, ensure_ascii=False))
        return 0

    if ir["version"] == 2:
        unsupported = [kind for kind in selected if kind not in CAPABILITIES[ir["profile"]]]
        if unsupported:
            print(json.dumps({"valid": False, "problems": [
                f"unsupported {ir['profile']} diagram with {kind}; choose {sorted(CAPABILITIES[ir['profile']])}"
                for kind in unsupported]}, ensure_ascii=False))
            return 1

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    archify_specification = render_archify(ir) if "archify" in selected else None
    if archify_specification and "webm" in exports["archify"]:
        archify_specification["meta"]["animation"] = "trace"
    native = {
        "mermaid": ("architecture.mmd", render_mermaid if ir["version"] == 1 else lambda value: render_view(value, "mermaid")),
        "plantuml": ("architecture.puml", render_plantuml if ir["version"] == 1 else lambda value: render_view(value, "plantuml")),
        "drawio": ("architecture.drawio", render_drawio if ir["version"] == 1 else lambda value: render_view(value, "drawio")),
        "archify": ("architecture.archify.json", lambda value: json.dumps(
            archify_specification, ensure_ascii=False, indent=2) + "\n"),
    }
    artifacts = {"architecture.ir.json": json.dumps(ir, ensure_ascii=False, indent=2) + "\n"}
    for kind in selected:
        filename, renderer = native[kind]
        artifacts[filename] = renderer(ir)
    desired = set(artifacts)
    desired.update(f"architecture.{kind}.{fmt}" for kind, formats in exports.items() for fmt in formats)
    if "archify" in selected:
        desired.add("architecture.archify.html")
    known = ("architecture.mmd", "architecture.puml", "architecture.drawio",
             "architecture.archify.json", "architecture.archify.html")
    known += tuple(f"architecture.{kind}.{fmt}" for kind, formats in EXPORT_FORMATS.items() for fmt in formats)
    for filename in known:
        if filename not in desired:
            (output / filename).unlink(missing_ok=True)
    for filename, content in artifacts.items():
        _write(output / filename, content)
    for kind, formats in exports.items():
        for fmt in formats:
            (output / f"architecture.{kind}.{fmt}").unlink(missing_ok=True)
    result = {"valid": True, "artifacts": [str(output / filename) for filename in artifacts],
              "archifyRendered": False, "rendererChecks": {}}
    if ir["version"] == 2:
        result["profile"] = ir["profile"]
        result["visualReview"] = "required"
    failures = []
    warnings = []
    if ir["version"] == 2 and ir["profile"].startswith("c4-") and "mermaid" in selected:
        warnings.append("Mermaid C4 syntax is experimental; inspect output and pin the Mermaid version")
    for kind, input_name in (("mermaid", "architecture.mmd"),
                             ("plantuml", "architecture.puml"),
                             ("drawio", "architecture.drawio")):
        if kind not in selected:
            continue
        target_svg = output / f"architecture.{kind}.svg"
        requested_formats = exports[kind]
        requested = getattr(args, f"{kind}_cli")
        executable = shutil.which(str(requested)) if requested else shutil.which(
            {"mermaid": "mmdc", "plantuml": "plantuml", "drawio": "drawio"}[kind])
        if not executable:
            required = bool(requested or requested_formats)
            result["rendererChecks"][kind] = "fail" if required else "skipped"
            if required:
                failures.append(f"{kind} CLI is unavailable: {requested or kind}")
            else:
                warnings.append(f"{kind} CLI is unavailable; {input_name} was not engine-validated")
            continue
        error = _check_diagram(kind, executable, output / input_name,
                               target_svg if "svg" in requested_formats else None)
        if not error:
            if "svg" in requested_formats:
                result["artifacts"].append(str(target_svg))
            for fmt in EXPORT_FORMATS[kind]:
                if fmt == "svg" or fmt not in requested_formats:
                    continue
                target = output / f"architecture.{kind}.{fmt}"
                export_error = _render_export(kind, executable, output / input_name, target, fmt)
                if export_error:
                    error = f"{fmt}: {export_error}"
                    break
                result["artifacts"].append(str(target))
        result["rendererChecks"][kind] = "fail" if error else "pass"
        if error:
            failures.append(f"official {kind} render failed: {error}")
    target = output / "architecture.archify.html"
    archify = None
    if "archify" in selected:
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
            if exports["archify"]:
                node = shutil.which("node")
                if not node:
                    failures.append("Node.js is required for Archify viewer exports")
                else:
                    with tempfile.TemporaryDirectory(dir=output) as directory:
                        requested_formats = [fmt for fmt in EXPORT_FORMATS["archify"] if fmt in exports["archify"]]
                        command = [node, str(Path(__file__).with_name("export_archify.mjs")),
                                   archify, str(target), directory, *requested_formats]
                        try:
                            exported = subprocess.run(command, text=True, capture_output=True, timeout=180)
                            if exported.returncode:
                                failures.append("official Archify viewer export failed: " +
                                                (exported.stderr.strip() or f"exit code {exported.returncode}"))
                            else:
                                for fmt in requested_formats:
                                    temporary = Path(directory) / f"architecture.archify.{fmt}"
                                    error = _check_export(temporary, fmt)
                                    if error:
                                        failures.append(f"official Archify {fmt} export failed: {error}")
                                        break
                                else:
                                    for fmt in requested_formats:
                                        destination = output / f"architecture.archify.{fmt}"
                                        (Path(directory) / destination.name).replace(destination)
                                        result["artifacts"].append(str(destination))
                        except (OSError, subprocess.TimeoutExpired) as error:
                            failures.append(f"official Archify viewer export failed: {error}")
        else:
            target.unlink(missing_ok=True)
            detail = process.stderr.strip() or (receipt.get("error") if isinstance(receipt, dict) else "")
            failures.append("official Archify delivery failed: " + (detail or "invalid delivery receipt or missing HTML"))
    elif "archify" in selected:
        warnings.append("Archify CLI is unavailable; schema-v1 JSON is ready for the official renderer")
        if args.archify_cli or exports["archify"]:
            failures.append(f"Archify CLI is unavailable: {args.archify_cli or 'archify'}")
    if warnings:
        result["warnings"] = warnings
    if failures:
        result["problems"] = failures
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
