"""tree-sitter fallback discovery engine.

Implements the discovery protocol (sync / source_files / locate) by building an
in-memory symbol index with tree-sitter grammars on demand. There is no
persistent index and no external CLI — parsing on demand means results are
always current. When the tree_sitter or grammar packages are not importable,
create_engine() returns None and engine selection falls through to no engine.

Symbol extraction follows the same approach as the understand-anything plugin's
per-language extractors: deterministic node-type dispatch over tree-sitter
trees with name-field capture, never regexes over source text.

locate() first indexes the generator's source roots; when a symbol is missing
there (the self-heal case, where the missing type lives outside the passed
roots) it expands once to the enclosing project root (nearest .git ancestor).
"""
import importlib
import os
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from discovery import DiscoveryEngine, SymbolLocation


JAVA_CLASS_NODES = {"class_declaration": "class", "interface_declaration": "interface",
                    "enum_declaration": "enum", "record_declaration": "class"}
JAVA_METHOD_NODES = {"method_declaration": "method", "constructor_declaration": "method"}
PYTHON_CLASS_NODES = {"class_definition": "class"}
PYTHON_FUNCTION_NODES = {"function_definition": "function"}

SOURCE_SUFFIXES = (".java", ".py")
SKIP_DIRECTORIES = {".git", ".idea", ".gradle", "node_modules", "build", "target",
                    "dist", "__pycache__", ".venv", "venv"}


def load_parsers() -> Dict[str, object]:
    """Load a tree-sitter parser per supported suffix; missing packages are skipped."""
    try:
        from tree_sitter import Language, Parser
    except ImportError:
        return {}
    parsers: Dict[str, object] = {}
    for suffix, module_name in ((".java", "tree_sitter_java"), (".py", "tree_sitter_python")):
        try:
            module = importlib.import_module(module_name)
            parsers[suffix] = Parser(Language(module.language()))
        except Exception:
            continue
    return parsers


def infer_project_root(roots: List[Path]) -> Path:
    for root in roots:
        for parent in [root, *root.parents]:
            if (parent / ".git").is_dir() or (parent / ".git").is_file():
                return parent
    if len(roots) == 1:
        return roots[0]
    return Path(os.path.commonpath([str(root) for root in roots]))


def walk_source_files(bases: List[Path], suffixes: Iterable[str] = SOURCE_SUFFIXES) -> List[Path]:
    wanted = tuple(suffixes)
    result: Set[Path] = set()
    for base in bases:
        for current, directories, files in os.walk(base):
            directories[:] = [name for name in directories if name not in SKIP_DIRECTORIES]
            for file_name in files:
                if file_name.endswith(wanted):
                    result.add(Path(current) / file_name)
    return sorted(result, key=str)


def _text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", "replace")


def _extract_java(root, source: bytes) -> List[Tuple[str, str, int, str]]:
    package = ""
    for child in root.children:
        if child.type == "package_declaration":
            for part in child.children:
                if part.type.endswith("identifier"):
                    package = _text(part, source)
    symbols: List[Tuple[str, str, int, str]] = []

    def visit(node):
        node_type = node.type
        kind = JAVA_CLASS_NODES.get(node_type)
        name_node = node.child_by_field_name("name") if kind or node_type in JAVA_METHOD_NODES else None
        if kind and name_node is not None:
            symbols.append((kind, _text(name_node, source), node.start_point[0] + 1, package))
        elif node_type in JAVA_METHOD_NODES and name_node is not None:
            symbols.append(("method", _text(name_node, source), node.start_point[0] + 1, package))
        for child in node.children:
            visit(child)

    visit(root)
    return symbols


def _extract_python(root, source: bytes) -> List[Tuple[str, str, int, str]]:
    symbols: List[Tuple[str, str, int, str]] = []

    def visit(node):
        kind = PYTHON_CLASS_NODES.get(node.type) or PYTHON_FUNCTION_NODES.get(node.type)
        if kind:
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                symbols.append((kind, _text(name_node, source), node.start_point[0] + 1, ""))
        for child in node.children:
            visit(child)

    visit(root)
    return symbols


EXTRACTORS = {".java": _extract_java, ".py": _extract_python}


class TreeSitterEngine(DiscoveryEngine):
    """On-demand tree-sitter symbol index; optional dependency, always fresh."""

    name = "tree-sitter"
    capabilities = frozenset({"sync", "source_files", "locate"})

    def __init__(self, roots: List[Path], project_root: Path, parsers: Dict[str, object]):
        # Resolve like the generator does, so located paths always match the
        # roots passed to the scanner (macOS /var vs /private/var symlinks).
        self._roots = [Path(root).resolve() for root in roots]
        self._project_root = Path(project_root).resolve()
        self._parsers = parsers
        self._index: Dict[str, List[SymbolLocation]] = {}
        self._parsed_paths: Set[Path] = set()
        self._parsed_everywhere = False

    def sync(self) -> bool:
        return True

    def source_files(self, suffix: str) -> List[Path]:
        return [path for path in walk_source_files(self._roots, (suffix,))]

    def locate(self, name: str, kinds: Optional[Iterable[str]] = None) -> List[SymbolLocation]:
        allowed = tuple(kinds) if kinds else None
        self._ensure_index(whole_project=False)
        if name not in self._index and not self._parsed_everywhere:
            self._ensure_index(whole_project=True)
        matches = [location for location in self._index.get(name, [])
                   if not allowed or location.kind in allowed]
        return sorted(matches, key=lambda location: (str(location.path), location.line))

    def _ensure_index(self, whole_project: bool) -> None:
        bases = [self._project_root] if whole_project else self._roots
        for path in walk_source_files(bases):
            if path in self._parsed_paths:
                continue
            self._parsed_paths.add(path)
            parser = self._parsers.get(path.suffix)
            extractor = EXTRACTORS.get(path.suffix)
            if parser is None or extractor is None:
                continue
            try:
                source = path.read_bytes()
                root_node = parser.parse(source).root_node
            except OSError:
                continue
            for kind, symbol_name, line, package in extractor(root_node, source):
                self._index.setdefault(symbol_name, []).append(SymbolLocation(
                    path, line, kind, symbol_name, package))
        if whole_project:
            self._parsed_everywhere = True


def create_engine(roots: List[Path]) -> Optional[TreeSitterEngine]:
    parsers = load_parsers()
    if not parsers:
        return None
    existing = [path for path in roots if path.exists()]
    if not existing:
        return None
    return TreeSitterEngine(existing, infer_project_root(existing), parsers)
