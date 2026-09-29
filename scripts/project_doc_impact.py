"""List document sections affected by source changes since its recorded revision."""

import argparse
import json
from pathlib import Path

from architecture_ir import _project_changes
from validate_project_doc import REVISION, SOURCE_REF, WEB_REF, _outline


def impact(source, document, changed=()):
    root = source.resolve()
    content = document.read_text(encoding="utf-8")
    revision = REVISION.search(content)
    if not revision or revision[1] == "非Git仓库":
        raise ValueError("文档缺少可比较的 Git 源代码版本")
    changes = _project_changes(root, revision[1])
    if changes is None:
        raise ValueError("无法比较文档记录的源代码版本与当前仓库")
    try:
        document_relative = document.resolve().relative_to(root).as_posix()
        changes.discard(document_relative)
    except ValueError:
        pass
    for item in changed:
        path = Path(item)
        if path.is_absolute():
            try:
                path = path.relative_to(root)
            except ValueError:
                pass
        changes.add(path.as_posix())
    _, sections = _outline(content)
    affected = []
    mapped = set()
    for name, lines in sections:
        references = {reference["path"] for reference in SOURCE_REF.finditer(WEB_REF.sub("", "\n".join(lines)))}
        normalized = set()
        for reference in references:
            path = Path(reference)
            if path.is_absolute():
                try:
                    path = path.relative_to(root)
                except ValueError:
                    continue
            normalized.add(path.as_posix())
        matched = changes & normalized
        if matched:
            affected.append(name)
            mapped.update(matched)
    unmapped = sorted(changes - mapped)
    return {"sourceRevision": revision[1], "changedFiles": sorted(changes),
            "affectedSections": affected, "unmappedChangedFiles": unmapped,
            "needsScopeReview": bool(unmapped)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--changed", type=Path, action="append", default=[], help="include a changed PRD or other file")
    args = parser.parse_args()
    try:
        result = impact(args.source, args.file, args.changed)
        status = 0
    except (OSError, UnicodeError, ValueError) as error:
        result = {"error": str(error)}
        status = 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
