#!/usr/bin/env python3
"""Validate and export an existing native diagram with its official engine."""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from architecture_ir import _check_evidence
from generate_architecture import EXPORT_FORMATS, _check_diagram, _check_export, _render_export


EXTENSIONS = {"mermaid": ".mmd", "plantuml": ".puml", "drawio": ".drawio",
              "archify": ".archify.json"}
BINARIES = {"mermaid": "mmdc", "plantuml": "plantuml", "drawio": "drawio",
            "archify": "archify"}
ARCHIFY_TYPES = {"architecture", "workflow", "sequence", "dataflow", "lifecycle"}
PROVENANCE = {"EXTRACTED", "INFERRED", "AMBIGUOUS"}


def _result(ok, engine, artifacts=(), **extra):
    print(json.dumps({"valid": ok, "engine": engine, "artifacts": [str(path) for path in artifacts],
                      "sourceEvidence": "not_checked", "visualReview": "required", **extra},
                     ensure_ascii=False, indent=2))
    return 0 if ok else 1


def _archify_export(binary, html, output, formats):
    node = shutil.which("node")
    if not node:
        return [], "Node.js is required for Archify viewer exports"
    with tempfile.TemporaryDirectory(dir=output) as directory:
        command = [node, str(Path(__file__).with_name("export_archify.mjs")), binary,
                   str(html), directory, *formats]
        try:
            process = subprocess.run(command, text=True, capture_output=True, timeout=180)
            if process.returncode:
                return [], process.stderr.strip() or f"Archify viewer exited {process.returncode}"
            for fmt in formats:
                source = Path(directory) / f"architecture.archify.{fmt}"
                error = _check_export(source, fmt)
                if error:
                    return [], f"{fmt}: {error}"
            paths = []
            for fmt in formats:
                source = Path(directory) / f"architecture.archify.{fmt}"
                target = output / f"diagram.archify.{fmt}"
                source.replace(target)
                paths.append(target)
            return paths, None
        except (OSError, subprocess.TimeoutExpired) as error:
            return [], str(error)


def _validate_source_manifest(path, root, source, engine, actual_type):
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        diagram_text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as error:
        return None, [f"evidence manifest or native source is unreadable: {error}"]
    if not isinstance(manifest, dict):
        return None, ["evidence manifest must be an object"]
    problems = []
    if manifest.get("version") != 1:
        problems.append("evidence manifest version must be 1")
    if manifest.get("engine") != engine:
        problems.append(f"evidence manifest engine must be {engine}")
    diagram_type = manifest.get("diagramType")
    if not isinstance(diagram_type, str) or not diagram_type.strip():
        problems.append("evidence manifest diagramType must be non-empty")
    elif actual_type and diagram_type != actual_type:
        problems.append(f"evidence manifest diagramType must be {actual_type}")
    claims = manifest.get("claims")
    if not isinstance(claims, list) or not claims:
        problems.append("evidence manifest claims must be a non-empty list")
        claims = []
    for index, claim in enumerate(claims):
        label = f"claims[{index}]"
        if not isinstance(claim, dict):
            problems.append(f"{label}: expected object")
            continue
        if not isinstance(claim.get("statement"), str) or not claim["statement"].strip():
            problems.append(f"{label}: statement must be non-empty")
        artifact_quote = claim.get("artifactQuote")
        if not isinstance(artifact_quote, str) or not artifact_quote.strip() or artifact_quote not in diagram_text:
            problems.append(f"{label}: artifactQuote must occur verbatim in native source")
        if claim.get("provenance") not in PROVENANCE:
            problems.append(f"{label}: provenance must be EXTRACTED, INFERRED, or AMBIGUOUS")
        _check_evidence(claim.get("evidence"), root, label, problems)
    return manifest, problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, choices=tuple(EXTENSIONS))
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--engine-cli", type=Path, help="require this official engine executable")
    parser.add_argument("--export", action="append", default=[],
                        help="requested output format; repeat for multiple formats")
    parser.add_argument("--quality", choices=("standard", "showcase"), default="standard",
                        help="Archify quality profile (default: standard)")
    parser.add_argument("--repo-root", type=Path, help="Archify architecture repository evidence root")
    parser.add_argument("--source-repo", type=Path, help="repository whose code supports the diagram claims")
    parser.add_argument("--evidence", type=Path, help="JSON manifest linking native diagram text to source code")
    args = parser.parse_args(argv)
    engine = args.engine
    source = args.input.resolve()
    output = args.output.resolve()
    if not source.is_file():
        parser.error(f"input file does not exist: {source}")
    required_suffix = ".json" if engine == "archify" else EXTENSIONS[engine]
    if not source.name.endswith(required_suffix):
        parser.error(f"{engine} input must end in {required_suffix}")
    formats = list(dict.fromkeys(args.export))
    invalid = [fmt for fmt in formats if fmt not in EXPORT_FORMATS[engine]]
    if invalid:
        parser.error(f"{engine} cannot export {invalid}; choose {EXPORT_FORMATS[engine]}")
    if args.repo_root and engine != "archify":
        parser.error("--repo-root applies only to Archify architecture")
    if args.quality != "standard" and engine != "archify":
        parser.error("--quality applies only to Archify")
    if bool(args.source_repo) != bool(args.evidence):
        parser.error("--source-repo and --evidence must be supplied together")
    diagram_type = None
    if engine == "archify":
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            parser.error(f"Archify JSON is unreadable: {error}")
        diagram_type = payload.get("diagram_type") if isinstance(payload, dict) else None
        if diagram_type not in ARCHIFY_TYPES:
            parser.error(f"unsupported Archify diagram_type: {diagram_type}")
        if args.repo_root and diagram_type != "architecture":
            parser.error("--repo-root applies only to Archify architecture")

    manifest = None
    if args.source_repo:
        source_root = args.source_repo.resolve()
        if not source_root.is_dir():
            parser.error(f"source repository does not exist: {source_root}")
        manifest, problems = _validate_source_manifest(args.evidence.resolve(), source_root,
                                                       source, engine, diagram_type)
        if problems:
            parser.error("; ".join(problems))

    metadata = {"sourceEvidence": "anchors_validated" if manifest else "not_checked",
                "claimSemantics": "not_proven" if manifest else "not_checked"}
    if manifest:
        metadata.update({"claimCount": len(manifest["claims"]),
                         "declaredDiagramType": manifest["diagramType"]})

    def report(ok, artifacts=(), **extra):
        return _result(ok, engine, artifacts, **metadata, **extra)

    executable = shutil.which(str(args.engine_cli)) if args.engine_cli else shutil.which(BINARIES[engine])
    if not executable:
        parser.error(f"official {engine} CLI is unavailable: {args.engine_cli or BINARIES[engine]}")

    output.mkdir(parents=True, exist_ok=True)
    native = output / ("diagram" + EXTENSIONS[engine])
    (output / "diagram.evidence.json").unlink(missing_ok=True)
    for fmt in EXPORT_FORMATS[engine]:
        (output / f"diagram.{engine}.{fmt}").unlink(missing_ok=True)
    if engine == "archify":
        (output / "diagram.archify.html").unlink(missing_ok=True)
    with tempfile.NamedTemporaryFile(dir=output, delete=False) as temporary:
        copied = Path(temporary.name)
    try:
        shutil.copyfile(source, copied)
        copied.replace(native)
    finally:
        copied.unlink(missing_ok=True)
    evidence_artifacts = []
    if manifest:
        evidence_copy = output / "diagram.evidence.json"
        evidence_copy.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        evidence_artifacts.append(evidence_copy)

    if engine == "archify":
        html = output / "diagram.archify.html"
        command = [executable, "deliver", diagram_type, str(native), str(html),
                   "--quality", args.quality, "--json"]
        if args.repo_root:
            command.extend(("--repo-root", str(args.repo_root.resolve())))
        try:
            process = subprocess.run(command, text=True, capture_output=True, timeout=180)
            receipt = json.loads(process.stdout)
        except (OSError, subprocess.TimeoutExpired, ValueError) as error:
            return report(False, evidence_artifacts, diagramType=diagram_type, officialCheck="fail",
                           problems=[str(error)])
        if (process.returncode or not html.is_file() or not isinstance(receipt, dict) or
                receipt.get("ok") is not True or receipt.get("command") != "deliver"):
            return report(False, evidence_artifacts, diagramType=diagram_type, officialCheck="fail",
                           problems=[process.stderr.strip() or str(receipt.get("error") if isinstance(receipt, dict) else "Archify delivery failed")])
        artifacts = [native, html, *evidence_artifacts]
        if formats:
            exported, error = _archify_export(executable, html, output, formats)
            if error:
                return report(False, artifacts, diagramType=diagram_type,
                               officialCheck="pass", exportCheck="fail", problems=[error])
            artifacts.extend(exported)
        return report(True, artifacts, diagramType=diagram_type,
                       officialCheck="pass", exportCheck="pass" if formats else "not_requested",
                       officialReceipt=receipt)

    error = _check_diagram(engine, executable, native,
                           output / f"diagram.{engine}.svg" if "svg" in formats else None)
    if error:
        return report(False, evidence_artifacts, officialCheck="fail", exportCheck="not_run", problems=[error])
    artifacts = [native, *evidence_artifacts]
    if "svg" in formats:
        artifacts.append(output / f"diagram.{engine}.svg")
    for fmt in formats:
        if fmt == "svg":
            continue
        target = output / f"diagram.{engine}.{fmt}"
        error = _render_export(engine, executable, native, target, fmt)
        if error:
            return report(False, artifacts, officialCheck="pass", exportCheck="fail",
                           problems=[f"{fmt}: {error}"])
        artifacts.append(target)
    return report(True, artifacts, officialCheck="pass",
                   exportCheck="pass" if formats else "not_requested")


if __name__ == "__main__":
    sys.exit(main())
