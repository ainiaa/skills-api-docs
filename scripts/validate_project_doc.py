"""Check the fixed outline of an Understand Project Markdown document."""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from generate_architecture import _check_export


TEMPLATES = {
    "project": "project-overview.md",
    "feature": "feature-description.md",
    "guide": "developer-guide.md",
    "architecture": "architecture-overview.md",
}
ARCHITECTURE_DIMENSIONS = (
    "服务与模块边界", "通信机制", "数据架构", "可观测性", "可扩展性",
)
HEADING = re.compile(r"^(#{1,2})\s+(.+?)\s*$")
TABLE_RULE = re.compile(r"^\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?$")
SOURCE_REF = re.compile(r"(?P<path>[\w./-]+)#L(?P<line>\d+)")
WEB_REF = re.compile(r"\[[^]]+\]\(https?://[^)]+\)")
IMAGE = re.compile(r"!\[[^]]*\]\((?:<([^>]+)>|([^)\s]+))\)")
LINK = re.compile(r"(?<!!)\[[^]]+\]\((?:<([^>]+)>|([^)\s]+))\)")
MERMAID = re.compile(r"(?ms)^```mermaid[^\n]*\n(.+?)^```[ \t]*$")
REVISION = re.compile(r"(?m)^>\s*源代码版本：\s*([0-9a-fA-F]{40}|[0-9a-fA-F]{64}|非Git仓库)\s*$")


def _outline(content):
    title = []
    sections = []
    current = None
    fence = None
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            fence = None if fence == marker else marker if fence is None else fence
            if current is not None:
                current[1].append(line)
            continue
        if fence:
            if current is not None:
                current[1].append(line)
            continue
        match = HEADING.match(line)
        if match and match[1] == "#":
            title.append(match[2])
        elif match and match[1] == "##":
            current = [match[2], []]
            sections.append(current)
        elif current is not None:
            current[1].append(line)
    return title, sections


def _empty_table(lines):
    table = []
    for line in [*lines, ""]:
        if line.strip().startswith("|"):
            table.append(line.strip())
            continue
        if len(table) == 2 and TABLE_RULE.fullmatch(table[1]):
            return True
        table = []
    return False


def _architecture_assessment_problems(sections):
    section = next((lines for name, lines in sections if name == "8. 架构评估"), [])
    table = []
    for line in section:
        if line.strip().startswith("|"):
            table.append(line.strip())
        elif table:
            break
    if len(table) < 3 or not TABLE_RULE.fullmatch(table[1]):
        return ["架构评分表缺失或格式无效"]
    rows = [tuple(cell.strip() for cell in line.strip("|").split("|")) for line in table[2:]]
    if tuple(row[0] for row in rows if row) != ARCHITECTURE_DIMENSIONS:
        return ["架构评分必须逐项覆盖五个固定维度"]
    problems = []
    for dimension, *cells in rows:
        if len(cells) != 2:
            problems.append(f"架构评分列数无效：{dimension}")
            continue
        score, basis = cells
        if score not in {"1", "2", "3", "4", "5", "待评估"}:
            problems.append(f"架构评分无效：{dimension}")
        if not basis or (score == "待评估" and basis == "待评估"):
            problems.append(f"架构评分缺少依据或待评估原因：{dimension}")
        elif score in {"1", "2", "3", "4", "5"} and not (SOURCE_REF.search(WEB_REF.sub("", basis)) or WEB_REF.search(basis)):
            problems.append(f"架构评分缺少来源：{dimension}")
    return problems


def _portable_file(target, document):
    path = Path(target)
    if target.startswith(("http://", "https://", "data:")) or document is None or path.is_absolute():
        return None
    path = document.parent / path
    path = path.resolve()
    return path if path.is_relative_to(document.parent.resolve()) and path.is_file() else None


def _ir_bundle_evidence(path, document, engine, images):
    if document is None:
        return "IR 交付目录未知"
    for parent in path.parents:
        if not parent.is_relative_to(document.parent.resolve()):
            break
        manifest = parent / "manifest.json"
        if not manifest.is_file():
            continue
        if not manifest.resolve().is_relative_to(document.parent.resolve()):
            return "IR 交付清单不在交付目录"
        try:
            report = json.loads(manifest.read_text(encoding="utf-8"))
            relative_source = path.relative_to(parent).as_posix()
            relative_images = {image.relative_to(parent).as_posix() for image in images
                               if image.is_relative_to(parent)}
        except (OSError, ValueError):
            return "IR 交付清单无法读取"
        if not isinstance(report, dict) or not isinstance(report.get("views"), dict):
            return "IR 交付清单格式无效"
        if report.get("coverageCheck") != "pass" or report.get("geometryCheck") != "pass":
            return "IR 交付清单未通过覆盖或几何校验"
        for view in report["views"].values():
            if (not isinstance(view, dict) or not isinstance(view.get("artifacts"), list)
                    or not all(isinstance(item, str) for item in view["artifacts"])
                    or not isinstance(view.get("rendererChecks"), dict)):
                return "IR 交付清单视图格式无效"
            artifacts = set(view.get("artifacts", []))
            if relative_source in artifacts:
                if view.get("rendererChecks", {}).get(engine) != "pass" or not artifacts.intersection(relative_images):
                    return "IR 交付清单未覆盖图源及图片"
                return None
        return "IR 交付清单未记录图源"
    return "证据清单缺失：diagram.evidence.json 或 IR manifest.json"


def _render_native_source(path, source=None, document=None, images=()):
    engine = ({".mmd": "mermaid", ".puml": "plantuml", ".drawio": "drawio"}.get(path.suffix.lower())
              or ("archify" if path.name.endswith(".archify.json") else None))
    if engine is None:
        return "不支持的图源格式"
    evidence = path.with_name("diagram.evidence.json") if source is not None else None
    if evidence is not None and document is not None and evidence.is_file() and not evidence.resolve().is_relative_to(document.parent.resolve()):
        return "证据清单不在交付目录"
    if evidence is not None and not evidence.is_file():
        error = _ir_bundle_evidence(path, document, engine, images)
        if error:
            return error
        evidence = None
    with tempfile.TemporaryDirectory() as directory:
        try:
            command = [sys.executable, str(Path(__file__).with_name("render_native_diagram.py")),
                       "--engine", engine, "--input", str(path), "--output", directory, "--export", "svg"]
            if evidence is not None:
                command.extend(("--source-repo", str(source), "--evidence", str(evidence)))
            process = subprocess.run(
                command,
                capture_output=True, text=True, timeout=180,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return str(error)
        if process.returncode:
            return (process.stdout + process.stderr).strip()[-500:] or "渲染器执行失败"
        if evidence is not None:
            try:
                report = json.loads(process.stdout)
            except ValueError:
                return "证据清单校验回执无效"
            if not isinstance(report, dict) or report.get("sourceEvidence") != "anchors_validated" or report.get("claimCoverage") != "complete":
                return "证据清单未覆盖全部图形事实"
    return None


def _architecture_diagram_problems(sections, document, check_diagrams=False, source=None):
    required = {"1. 系统全景": "系统架构全景图", "2. 核心流程": "核心流程图"}
    problems = []
    for name, lines in sections:
        for image in IMAGE.finditer("\n".join(lines)):
            target = image[1] or image[2]
            path = _portable_file(target, document)
            if path is None or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif"}:
                problems.append(f"本地图片缺失或不在交付目录：{target}")
                continue
            try:
                if path.suffix.lower() == ".gif":
                    with path.open("rb") as file:
                        valid = file.read(6) in (b"GIF87a", b"GIF89a")
                    error = None if valid else "invalid GIF"
                else:
                    error = _check_export(path, "jpg" if path.suffix.lower() == ".jpeg" else path.suffix.lower()[1:])
            except OSError as failure:
                error = str(failure)
            if error:
                problems.append(f"本地图片格式无效：{target}：{error}")
    for name, lines in sections:
        label = required.get(name, name)
        body = "\n".join(lines)
        images = list(IMAGE.finditer(body))
        mermaid = [match[1] for match in MERMAID.finditer(body) if match[1].strip()]
        has_diagram = bool(mermaid or images)
        if name in required and not has_diagram:
            problems.append(f"缺少{label}：{name}")
        if not check_diagrams:
            continue
        for index, diagram in enumerate(mermaid, 1):
            with tempfile.TemporaryDirectory() as directory:
                native = Path(directory) / "inline.mmd"
                native.write_text(diagram, encoding="utf-8")
                error = _render_native_source(native)
            if error:
                problems.append(f"{label} Mermaid 渲染失败（第 {index} 张）：{error}")
        if images:
            image_paths = [_portable_file(image[1] or image[2], document) for image in images]
            image_paths = [path for path in image_paths if path is not None]
            sources = []
            for link in LINK.finditer(body):
                target = link[1] or link[2]
                if target.lower().endswith((".mmd", ".puml", ".drawio", ".archify.json")):
                    path = _portable_file(target, document)
                    if path is None:
                        problems.append(f"可编辑图源缺失或不在交付目录：{target}")
                    else:
                        sources.append(path)
            if not sources:
                problems.append(f"缺少{label}的本地可编辑图源：{name}")
            for path in set(sources):
                error = _render_native_source(path, source, document, image_paths)
                if error:
                    problems.append(f"可编辑图源渲染失败：{path.name}：{error}")
    return problems


def _source_problems(content, sections, source):
    problems = []
    root = source.resolve()
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True)
    current = head.stdout.strip() if head.returncode == 0 else "非Git仓库"
    match = REVISION.search(content)
    if not match or match[1] != current:
        problems.append(f"源代码版本缺失或已过期；当前版本：{current}")
    for name, lines in sections:
        body = "\n".join(lines)
        references = list(SOURCE_REF.finditer(WEB_REF.sub("", body)))
        meaningful = [line.strip() for line in lines if line.strip() and not line.strip().startswith(("<!--", "###"))]
        unknown_only = meaningful and all("待确认" in line or "暂无已知项" in line for line in meaningful)
        if not references and not WEB_REF.search(body) and not unknown_only:
            problems.append(f"章节缺少来源：{name}")
        for reference in references:
            path = Path(reference["path"])
            path = path if path.is_absolute() else root / path
            try:
                line_count = len(path.read_text(encoding="utf-8").splitlines())
            except (OSError, UnicodeError):
                problems.append(f"来源文件无法读取：{reference[0]}")
                continue
            if int(reference["line"]) < 1 or int(reference["line"]) > line_count:
                problems.append(f"来源行号无效：{reference[0]}")
    return problems


def validate(kind, content, source=None, document=None, check_diagrams=False):
    template = Path(__file__).resolve().parents[1] / "skills" / "understand-project" / "assets" / TEMPLATES[kind]
    template_titles, template_sections = _outline(template.read_text(encoding="utf-8"))
    titles, sections = _outline(content)
    problems = []
    if len(titles) != 1 or not titles[0].strip() or titles == template_titles:
        problems.append("标题必须替换模板占位名，且全文只能有一个一级标题")
    expected = [name for name, _ in template_sections]
    actual = [name for name, _ in sections]
    if actual != expected:
        problems.append(f"章节必须按模板保留名称和顺序：{expected}")
    if "<!-- TEMPLATE:" in content:
        problems.append("仍有模板提示未移除")
    for name, lines in sections:
        meaningful = [line for line in lines if line.strip() and not line.strip().startswith("<!--")]
        if not meaningful or (len(meaningful) == 2 and _empty_table(meaningful)):
            problems.append(f"空章节：{name}")
        if _empty_table(lines):
            problems.append(f"空表格：{name}")
    if kind == "architecture":
        problems.extend(_architecture_assessment_problems(sections))
        problems.extend(_architecture_diagram_problems(sections, document, check_diagrams, source))
    if source is not None:
        problems.extend(_source_problems(content, sections, source))
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=TEMPLATES, required=True)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--source", type=Path, help="strict mode: check source revision and cited source lines")
    parser.add_argument("--check-diagrams", action="store_true", help="render architecture diagrams with official engines")
    args = parser.parse_args()
    try:
        content = args.file.read_text(encoding="utf-8")
        if args.source and not args.source.is_dir():
            raise OSError("--source must be an existing directory")
        problems = validate(args.kind, content, args.source, args.file, args.check_diagrams)
    except (OSError, UnicodeError) as error:
        problems = [f"无法读取文档：{error}"]
    print(json.dumps({"valid": not problems, "kind": args.kind, "file": str(args.file),
                      "problems": problems}, ensure_ascii=False))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
