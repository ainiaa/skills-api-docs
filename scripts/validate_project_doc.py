"""Check the fixed outline of an Understand Project Markdown document."""

import argparse
import json
import re
import subprocess
from pathlib import Path


TEMPLATES = {
    "project": "project-overview.md",
    "feature": "feature-description.md",
    "guide": "developer-guide.md",
}
HEADING = re.compile(r"^(#{1,2})\s+(.+?)\s*$")
TABLE_RULE = re.compile(r"^\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?$")
SOURCE_REF = re.compile(r"(?P<path>[\w./-]+)#L(?P<line>\d+)")
WEB_REF = re.compile(r"\[[^]]+\]\(https?://[^)]+\)")
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


def validate(kind, content, source=None):
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
    if source is not None:
        problems.extend(_source_problems(content, sections, source))
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=TEMPLATES, required=True)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--source", type=Path, help="strict mode: check source revision and cited source lines")
    args = parser.parse_args()
    try:
        content = args.file.read_text(encoding="utf-8")
        if args.source and not args.source.is_dir():
            raise OSError("--source must be an existing directory")
        problems = validate(args.kind, content, args.source)
    except (OSError, UnicodeError) as error:
        problems = [f"无法读取文档：{error}"]
    print(json.dumps({"valid": not problems, "kind": args.kind, "file": str(args.file),
                      "problems": problems}, ensure_ascii=False))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
