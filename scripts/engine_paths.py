"""Resolve official renderers installed on PATH or by this skill group."""

import os
import shutil
from pathlib import Path


ENGINE_BINARIES = {"mermaid": "mmdc", "plantuml": "plantuml",
                   "drawio": "drawio", "archify": "archify"}


def renderer_home():
    configured = os.environ.get("UNDERSTAND_RENDERER_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".local/share/understand-skills/renderers"


def find_engine(engine, explicit=None):
    if engine not in ENGINE_BINARIES:
        raise ValueError(f"unknown renderer: {engine}")
    if explicit is not None:
        return shutil.which(str(explicit))
    system = shutil.which(ENGINE_BINARIES[engine])
    if system:
        return system
    managed = renderer_home() / "bin" / ENGINE_BINARIES[engine]
    return str(managed) if managed.is_file() and os.access(managed, os.X_OK) else None


def prepare_runtime():
    """Let managed Node power its renderers without changing the user's shell PATH."""
    node_bin = renderer_home() / "runtime" / "node-v22.13.1" / "bin"
    if (node_bin / "node").is_file():
        os.environ["PATH"] = str(node_bin) + os.pathsep + os.environ.get("PATH", "")
