"""tree-sitter fallback discovery engine.

Implements the discovery protocol (sync / source_files / locate) by building an
in-memory symbol index with tree-sitter grammars on demand. There is no
persistent index and no external CLI — parsing on demand means results are
always current. When the tree_sitter or grammar packages are not importable,
create_engine() returns None and engine selection falls through to no engine.

Symbol extraction follows the official tree-sitter tags.scm convention: every
declaration captures `@name` (the name identifier) paired with
`@definition.<kind>` (the declaration), and the two are joined per match via
matches(). The kind suffix becomes the protocol kind. Main queries are vendored
verbatim from each grammar's upstream tags.scm where one exists; supplementary
extra.scm files carry what upstream does not capture (the Java package name,
TypeScript concrete declarations) and are concatenated at load time. Grouped
matches() is used exactly where pairing is needed.
"""
import hashlib
import importlib
import json
import os
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from discovery import DiscoveryEngine, SymbolLocation


SKIP_DIRECTORIES = {".git", ".idea", ".gradle", "node_modules", "build", "target",
                    "dist", "__pycache__", ".venv", "venv"}

GRAMMAR_MODULES = {
    ".java": ("tree_sitter_java", "language", "java"),
    ".py": ("tree_sitter_python", "language", "python"),
    ".ts": ("tree_sitter_typescript", "language_typescript", "typescript"),
    ".tsx": ("tree_sitter_typescript", "language_tsx", "tsx"),
    ".go": ("tree_sitter_go", "language", "go"),
    ".php": ("tree_sitter_php", "language_php", "php"),
}

# Tag queries live in scripts/queries/<language>/: tags.scm is the main query —
# vendored verbatim from the grammar's upstream tags.scm where one exists (Go,
# PHP, TypeScript) or in the same shape for grammars without one (Java,
# Python) — and optional extra.scm holds supplementary patterns (the Java
# package capture, the TypeScript concrete declarations the signature-oriented
# upstream file omits). Adding a language means adding a grammar module, a
# query directory, and vendoring its upstream tags.scm.
QUERY_DIRECTORY = Path(__file__).with_name("queries")

SOURCE_SUFFIXES = tuple(GRAMMAR_MODULES)

KIND_PREFIX = "definition."
PACKAGE_CAPTURE = "package"

CACHE_VERSION = 1


def _query_hash(query_texts) -> str:
    """Cache namespace derived from the loaded query texts; query edits invalidate caches."""
    return hashlib.sha256(repr(sorted(query_texts)).encode("utf-8")).hexdigest()[:12]


def _cache_path(project_root: Path, query_hash: str) -> Path:
    digest = hashlib.sha256(str(project_root).encode("utf-8")).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / "api-savior-docs" / "tree-sitter-index" / (digest + "-" + query_hash + ".json")


def _matches(query, node) -> List[Dict[str, list]]:
    """Grouped matches with every capture value normalized to a list.

    Tolerates py-tree-sitter versions before QueryCursor; value normalization
    absorbs the Node-vs-list difference across versions.
    """
    try:
        from tree_sitter import QueryCursor
    except ImportError:
        matches = query.matches(node)
    else:
        matches = QueryCursor(query).matches(node)
    return [dict((key, value if isinstance(value, list) else [value])
                 for key, value in captures.items())
            for _, captures in matches]


def _captures(query, node) -> Dict[str, list]:
    """Flat capture view, for single-capture queries where no pairing is needed."""
    try:
        from tree_sitter import QueryCursor
    except ImportError:
        return query.captures(node)
    return QueryCursor(query).captures(node)


def load_parsers() -> Dict[str, dict]:
    """Compile a parser plus its tag query per supported suffix; missing packages or query files are skipped."""
    try:
        from tree_sitter import Language, Parser, Query
    except ImportError:
        return {}
    engines: Dict[str, dict] = {}
    for suffix, (module_name, factory_name, query_directory) in GRAMMAR_MODULES.items():
        try:
            module = importlib.import_module(module_name)
            language = Language(getattr(module, factory_name)())
            directory = QUERY_DIRECTORY / query_directory
            text = (directory / "tags.scm").read_text(encoding="utf-8")
            extra = directory / "extra.scm"
            if extra.is_file():
                text += "\n" + extra.read_text(encoding="utf-8")
            engines[suffix] = {
                "parser": Parser(language),
                "tags": Query(language, text),
                "text": text,
            }
        except Exception:
            continue
    return engines


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


def extract_symbols(root, source: bytes, queries: Dict[str, object]) -> List[Tuple[str, str, int, str]]:
    """Return (kind, name, line, package) tuples per the tags.scm pairing convention."""
    captures_by_name = _captures(queries["tags"], root)
    package = ""
    package_nodes = captures_by_name.get(PACKAGE_CAPTURE)
    if package_nodes:
        package = _text(package_nodes[0], source)
    symbols: List[Tuple[str, str, int, str]] = []
    for captures in _matches(queries["tags"], root):
        names = captures.get("name")
        kinds = [key[len(KIND_PREFIX):] for key in captures if key.startswith(KIND_PREFIX)]
        if not names or not kinds:
            continue
        name_node = names[0]
        symbols.append((kinds[0], _text(name_node, source), name_node.start_point[0] + 1, package))
    return symbols


class TreeSitterEngine(DiscoveryEngine):
    """On-demand tree-sitter symbol index; optional dependency, always fresh."""

    name = "tree-sitter"
    capabilities = frozenset({"sync", "source_files", "locate"})

    def __init__(self, roots: List[Path], project_root: Path, parsers: Dict[str, dict]):
        # Resolve like the generator does, so located paths always match the
        # roots passed to the scanner (macOS /var vs /private/var symlinks).
        self._roots = [Path(root).resolve() for root in roots]
        self._project_root = Path(project_root).resolve()
        self._parsers = parsers
        self._query_hash = _query_hash([config["text"] for config in parsers.values()])
        self._index: Dict[str, List[SymbolLocation]] = {}
        self._parsed_paths: Set[Path] = set()
        self._parsed_everywhere = False
        self._file_cache: Optional[Dict[str, dict]] = None
        self._cache_dirty = False

    def _load_cache(self) -> Dict[str, dict]:
        """Per-file extraction cache keyed by mtime+size; any problem means no cache."""
        if self._file_cache is None:
            try:
                data = json.loads(_cache_path(self._project_root, self._query_hash).read_text(encoding="utf-8"))
                self._file_cache = data.get("files", {}) if data.get("version") == CACHE_VERSION else {}
            except (OSError, ValueError):
                self._file_cache = {}
        return self._file_cache

    def _store_cache(self) -> None:
        if not self._cache_dirty:
            return
        try:
            path = _cache_path(self._project_root, self._query_hash)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"version": CACHE_VERSION, "files": self._file_cache}),
                                 encoding="utf-8")
            temporary.replace(path)
        except OSError:
            pass
        self._cache_dirty = False

    def _file_symbols(self, path: Path, config: Dict[str, object]) -> List[Tuple[str, str, int, str]]:
        cache = self._load_cache()
        try:
            stat = path.stat()
        except OSError:
            return []
        entry = cache.get(str(path))
        if entry and entry.get("mtime") == stat.st_mtime and entry.get("size") == stat.st_size:
            return [tuple(item) for item in entry.get("symbols", [])]
        try:
            source = path.read_bytes()
            root_node = config["parser"].parse(source).root_node
        except OSError:
            return []
        symbols = extract_symbols(root_node, source, config)
        cache[str(path)] = {"mtime": stat.st_mtime, "size": stat.st_size,
                            "symbols": [list(item) for item in symbols]}
        self._cache_dirty = True
        return symbols

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
            config = self._parsers.get(path.suffix)
            if config is None:
                continue
            for kind, symbol_name, line, package in self._file_symbols(path, config):
                self._index.setdefault(symbol_name, []).append(SymbolLocation(
                    path, line, kind, symbol_name, package))
        self._store_cache()
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
