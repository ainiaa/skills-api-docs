"""Engine-agnostic code-discovery layer.

A discovery engine answers location queries only — where source files live,
where a symbol is defined. It never interprets semantics: field extraction,
wire names, and enum binding stay in the language adapters, and every engine
failure degrades to the plain filesystem behavior of the generator.

Backends:
- CodeGraphEngine: shells out to the codegraph CLI when the project is indexed.
- TreeSitterEngine: builds an in-memory symbol index with tree-sitter grammars.
- NullEngine: filesystem walk; locate() always misses, so engine-assisted flows
  no-op and the generator behaves exactly as without this module.
- FakeEngine: in-memory backend for tests, driven by a JSON manifest.
"""
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from typing import NamedTuple


CLASS_KINDS = ("class", "struct", "interface", "trait", "protocol", "enum")
METHOD_KINDS = ("method", "function")

FAKE_ENGINE_ENV = "API_SAVIOR_FAKE_ENGINE"


class SymbolLocation(NamedTuple):
    path: Path
    line: int
    kind: str
    name: str
    qualified_name: str


class DiscoveryEngine:
    """Protocol every discovery backend implements; defaults are the null behavior."""

    name = "null"
    capabilities: frozenset = frozenset()

    def sync(self) -> bool:
        return False

    def source_files(self, suffix: str) -> List[Path]:
        return []

    def locate(self, name: str, kinds: Optional[Iterable[str]] = None) -> List[SymbolLocation]:
        return []

    def locate_many(self, names: List[str], kinds: Optional[Iterable[str]] = None) -> Dict[str, List[SymbolLocation]]:
        """Batch location; engines may override with a parallel or native batch implementation."""
        return {name: self.locate(name, kinds) for name in names}


class NullEngine(DiscoveryEngine):
    """Filesystem-only fallback; engine-assisted flows naturally no-op."""

    name = "null"

    def __init__(self, roots: List[Path]):
        self._roots = list(roots)

    def source_files(self, suffix: str) -> List[Path]:
        return sorted({path for root in self._roots for path in root.rglob("*" + suffix)
                       if path.is_file()}, key=str)


class CodeGraphEngine(DiscoveryEngine):
    """codegraph CLI backend; every CLI detail stays inside this class."""

    name = "codegraph"
    capabilities = frozenset({"sync", "source_files", "locate"})

    def __init__(self, project_root: Path, binary: str):
        self._project_root = project_root
        self._binary = binary
        self._broken = False

    def sync(self) -> bool:
        if self._broken:
            return False
        try:
            subprocess.run([self._binary, "sync", "-q", str(self._project_root)],
                           check=True, text=True, capture_output=True, timeout=180)
            return True
        except (OSError, subprocess.SubprocessError) as error:
            self._broken = True
            print(f"[{self.name}] sync failed; skipping discovery: {error}", file=sys.stderr)
            return False

    def _query(self, arguments: List[str]):
        if self._broken:
            return None
        try:
            command = [self._binary, *arguments, "-p", str(self._project_root)]
            completed = subprocess.run(command, check=True, text=True, capture_output=True, timeout=120)
            return json.loads(completed.stdout)
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            self._broken = True
            print(f"[{self.name}] discovery disabled after error: {error}", file=sys.stderr)
            return None

    def locate(self, name: str, kinds: Optional[Iterable[str]] = None) -> List[SymbolLocation]:
        payload = self._query(["query", name, "--json"])
        if not payload:
            return []
        allowed = tuple(kinds) if kinds else None
        matches = set()
        for item in payload:
            node = item.get("node", {}) if isinstance(item, dict) else {}
            if node.get("name") != name or (allowed and node.get("kind") not in allowed):
                continue
            relative = node.get("filePath", "")
            if not relative:
                continue
            matches.add(SymbolLocation((self._project_root / relative).resolve(),
                                       int(node.get("startLine") or 0), node.get("kind", ""),
                                       node.get("name", ""), node.get("qualifiedName", "")))
        return sorted(matches, key=lambda location: (str(location.path), location.line))

    def locate_many(self, names: List[str], kinds: Optional[Iterable[str]] = None) -> Dict[str, List[SymbolLocation]]:
        """Run one CLI query per name, in parallel threads (each query is a subprocess)."""
        names = list(names)
        if len(names) <= 1:
            return {name: self.locate(name, kinds) for name in names}
        with ThreadPoolExecutor(max_workers=min(8, len(names))) as executor:
            results = executor.map(lambda name: self.locate(name, kinds), names)
        return dict(zip(names, results))

    def source_files(self, suffix: str) -> List[Path]:
        payload = self._query(["files", "--json"])
        if not payload:
            return []
        result = set()
        for item in payload:
            relative = item.get("path", "") if isinstance(item, dict) else ""
            if relative.endswith(suffix):
                candidate = (self._project_root / relative).resolve()
                if candidate.is_file():
                    result.add(candidate)
        return sorted(result, key=str)


class FakeEngine(DiscoveryEngine):
    """In-memory backend for tests; the manifest mirrors the protocol data shapes."""

    name = "fake"
    capabilities = frozenset({"sync", "source_files", "locate"})

    def __init__(self, manifest: dict, project_root: Optional[Path] = None):
        self._project_root = Path(project_root) if project_root else Path.cwd()
        self._locate: Dict[str, list] = manifest.get("locate", {})
        self._files: List[str] = manifest.get("files", [])
        self.sync_calls = 0
        self.locate_calls: List[str] = []

    def sync(self) -> bool:
        self.sync_calls += 1
        return True

    def locate(self, name: str, kinds: Optional[Iterable[str]] = None) -> List[SymbolLocation]:
        self.locate_calls.append(name)
        allowed = tuple(kinds) if kinds else None
        matches = set()
        for entry in self._locate.get(name, []):
            if allowed and entry.get("kind") not in allowed:
                continue
            path = Path(entry["path"])
            if not path.is_absolute():
                path = self._project_root / path
            matches.add(SymbolLocation(path.resolve(), int(entry.get("line") or 0),
                                       entry.get("kind", ""), entry.get("name", name),
                                       entry.get("qualified_name", "")))
        return sorted(matches, key=lambda location: (str(location.path), location.line))

    def source_files(self, suffix: str) -> List[Path]:
        result = set()
        for path in self._files:
            if path.endswith(suffix):
                candidate = Path(path)
                if not candidate.is_absolute():
                    candidate = self._project_root / candidate
                result.add(candidate.resolve())
        return sorted(result, key=str)


def find_project_root(roots: List[Path]) -> Optional[Path]:
    for root in roots:
        for parent in [root, *root.parents]:
            if (parent / ".codegraph").is_dir():
                return parent
    return None


def select_engine(roots: List[Path], enabled: bool = True) -> Optional[DiscoveryEngine]:
    """Pick a discovery engine for the source roots; None disables discovery features.

    Selection order: codegraph (when the project is indexed and the CLI exists),
    then the tree-sitter fallback (optional pip dependency), then None.
    """
    if not enabled:
        return None
    fake = os.environ.get(FAKE_ENGINE_ENV)
    if fake:
        manifest = json.loads(Path(fake).read_text(encoding="utf-8"))
        return FakeEngine(manifest, manifest.get("project_root"))
    codegraph = _select_codegraph(roots)
    if codegraph is not None:
        return codegraph
    try:
        from tree_sitter_engine import create_engine as create_tree_sitter_engine
    except ImportError:
        return None
    return create_tree_sitter_engine(roots)


def _select_codegraph(roots: List[Path]) -> Optional[DiscoveryEngine]:
    project_root = find_project_root(roots)
    if project_root is None:
        return None
    binary = shutil.which("codegraph")
    if binary is None:
        print(f"[discovery] {project_root / '.codegraph'} exists but the codegraph CLI "
              "is not installed; skipping discovery", file=sys.stderr)
        return None
    engine = CodeGraphEngine(project_root, binary)
    if not engine.sync():
        return None
    return engine
