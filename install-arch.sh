#!/usr/bin/env bash
set -euo pipefail

REPOSITORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SOURCE="$REPOSITORY/skills/understand-arch"
TARGET="${CODEX_HOME:-${HOME}/.codex}/skills/understand-arch"

same_install() {
  [[ -L "$TARGET" ]] || return 1
  [[ "$(cd "$TARGET" 2>/dev/null && pwd -P)" == "$SOURCE" ]]
}

case "${1:-}" in
  ""|--install)
    [[ -f "$SOURCE/SKILL.md" && -f "$REPOSITORY/scripts/generate_architecture.py" ]] || {
      echo "Error: incomplete understand-arch checkout" >&2; exit 1;
    }
    if same_install; then echo "understand-arch is already installed → $TARGET"; exit 0; fi
    if [[ -e "$TARGET" || -L "$TARGET" ]]; then
      echo "Error: refusing to replace existing path: $TARGET" >&2; exit 1
    fi
    mkdir -p "$(dirname "$TARGET")"
    ln -s "$SOURCE" "$TARGET"
    echo "Installed understand-arch → $TARGET"
    ;;
  --doctor)
    if same_install; then echo "understand-arch is installed → $TARGET"; else
      echo "understand-arch is not linked to this checkout: $TARGET" >&2; exit 1
    fi
    ;;
  --uninstall)
    if same_install; then rm "$TARGET"; echo "Uninstalled understand-arch → $TARGET"
    elif [[ -e "$TARGET" || -L "$TARGET" ]]; then
      echo "Error: refusing to remove unrelated path: $TARGET" >&2; exit 1
    else
      echo "understand-arch is not installed at $TARGET"
    fi
    ;;
  --help|-h)
    echo "Usage: bash install-arch.sh [--install|--doctor|--uninstall]"
    ;;
  *)
    echo "Usage: bash install-arch.sh [--install|--doctor|--uninstall]" >&2; exit 2
    ;;
esac
