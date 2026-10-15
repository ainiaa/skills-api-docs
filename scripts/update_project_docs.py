#!/usr/bin/env python3
"""Fast-forward this collection, then run the updated dependency installer."""

import argparse
import subprocess
import sys
from pathlib import Path

from python_runtime import require_python


def git(source, *arguments):
    result = subprocess.run(["git", "-C", str(source), *arguments], capture_output=True,
                            text=True, timeout=120)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def update(source, arguments):
    source = source.resolve()
    if Path(git(source, "rev-parse", "--show-toplevel")).resolve() != source:
        raise RuntimeError("the collection must be its own Git checkout")
    if git(source, "status", "--porcelain"):
        raise RuntimeError("local changes exist; commit or stash them before updating")
    git(source, "symbolic-ref", "--quiet", "--short", "HEAD")
    git(source, "rev-parse", "--verify", "@{upstream}")
    print(git(source, "pull", "--ff-only", "--no-rebase"), flush=True)
    print("Collection checkout updated; synchronizing child skills and dependencies.", flush=True)
    # Execute the new installer in a fresh process after its files may have changed.
    result = subprocess.run(["bash", str(source / "install.sh"), "--update-deps", *arguments])
    if result.returncode:
        raise RuntimeError("checkout update succeeded, but dependency/skill synchronization failed; rerun install.sh --update-deps after resolving the error")


def main(argv=None):
    require_python()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=("codex", "claude", "zcode", "dsh", "gemini", "grok", "pi", "opencode", "both", "all"), default="both")
    parser.add_argument("--engine", choices=("mermaid", "plantuml", "drawio", "archify"), action="append")
    parser.add_argument("--no-engines", action="store_true")
    args = parser.parse_args(argv)
    if args.engine and args.no_engines:
        parser.error("--engine and --no-engines cannot be combined")
    arguments = ["--host", args.host]
    for engine in args.engine or []:
        arguments.extend(("--engine", engine))
    if args.no_engines:
        arguments.append("--no-engines")
    try:
        update(Path(__file__).resolve().parents[1], arguments)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Collection update failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
