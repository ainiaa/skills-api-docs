#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SKILLS_DIR="${CODEX_HOME:-${HOME}/.codex}/skills"
TARGET="$SKILLS_DIR/api-savior-docs"

usage() {
  cat <<'EOF'
API Savior Docs installer

Usage:
  bash install.sh              Install the current checkout in Codex
  bash install.sh --doctor     Check whether this checkout is installed
  bash install.sh --uninstall  Remove this checkout's Codex skill link
  bash install.sh --help       Show this help

Installation links the current checkout into ${CODEX_HOME:-$HOME/.codex}/skills.
Existing directories, files, and unrelated symlinks are never replaced.
EOF
}

same_install() {
  [[ -L "$TARGET" ]] || return 1
  local resolved
  resolved="$(cd "$TARGET" 2>/dev/null && pwd -P)" || return 1
  [[ "$resolved" == "$SOURCE_DIR" ]]
}

if [[ $# -gt 1 ]]; then
  usage >&2
  exit 2
fi

case "${1:-}" in
  ""|--install)
    if [[ ! -f "$SOURCE_DIR/SKILL.md" || ! -f "$SOURCE_DIR/VERSION" || ! -f "$SOURCE_DIR/scripts/generate_api_docs.py" ]]; then
      echo "Error: incomplete skill checkout: $SOURCE_DIR" >&2
      exit 1
    fi
    if same_install; then
      echo "api-savior-docs is already installed → $TARGET"
      exit 0
    fi
    if [[ -e "$TARGET" || -L "$TARGET" ]]; then
      echo "Error: refusing to replace existing path: $TARGET" >&2
      exit 1
    fi
    mkdir -p "$SKILLS_DIR"
    ln -s "$SOURCE_DIR" "$TARGET"
    echo "Installed api-savior-docs → $TARGET"
    ;;
  --doctor)
    version=""
    if [[ -f "$SOURCE_DIR/VERSION" ]]; then
      version="$(head -1 "$SOURCE_DIR/VERSION")"
    fi
    if same_install; then
      if [[ -n "$version" ]]; then
        echo "api-savior-docs $version is installed → $TARGET"
      else
        echo "api-savior-docs is installed → $TARGET"
      fi
    else
      echo "api-savior-docs is not linked to this checkout: $TARGET" >&2
      exit 1
    fi
    ;;
  --uninstall)
    if same_install; then
      rm "$TARGET"
      echo "Uninstalled api-savior-docs → $TARGET"
    elif [[ -e "$TARGET" || -L "$TARGET" ]]; then
      echo "Error: refusing to remove an unrelated path: $TARGET" >&2
      exit 1
    else
      echo "api-savior-docs is not installed at $TARGET"
    fi
    ;;
  --help|-h)
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
