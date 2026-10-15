#!/usr/bin/env bash
set -euo pipefail

REPOSITORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SOURCE="$REPOSITORY/skills/project-docs-diagram"
TARGET="${CODEX_HOME:-${HOME}/.codex}/skills/project-docs-diagram"
OLD_NAMES=(understand-api-arch understand-arch)
OLD_SOURCES=("$REPOSITORY/skills/understand-api-arch" "$REPOSITORY/skills/understand-arch")

same_install() {
  [[ -L "$TARGET" ]] || return 1
  [[ "$(cd "$TARGET" 2>/dev/null && pwd -P)" == "$SOURCE" ]]
}

old_install() {
  local target="$1" source="$2" link parent
  [[ -L "$target" ]] || return 1
  link="$(readlink "$target")"
  [[ "$link" == /* ]] || link="$(dirname "$target")/$link"
  parent="$(cd "$(dirname "$link")" 2>/dev/null && pwd -P)" || return 1
  [[ "$parent/$(basename "$link")" == "$source" ]]
}

clean_old_links() {
  local index target
  for index in "${!OLD_NAMES[@]}"; do
    target="$(dirname "$TARGET")/${OLD_NAMES[$index]}"
    if old_install "$target" "${OLD_SOURCES[$index]}"; then
      if [[ "${1:-}" == --check ]]; then return 1; fi
      rm "$target"
      echo "Removed old skill link → $target"
    fi
  done
}

case "${1:-}" in
  ""|--install)
    [[ -f "$SOURCE/SKILL.md" && -f "$REPOSITORY/scripts/generate_architecture.py" ]] || {
      echo "Error: incomplete project-docs-diagram checkout" >&2; exit 1;
    }
    if ! same_install && [[ -e "$TARGET" || -L "$TARGET" ]]; then
      echo "Error: refusing to replace existing path: $TARGET" >&2; exit 1
    fi
    if same_install; then
      echo "project-docs-diagram is already installed → $TARGET"
    else
      mkdir -p "$(dirname "$TARGET")"
      ln -s "$SOURCE" "$TARGET"
      echo "Installed project-docs-diagram → $TARGET"
    fi
    clean_old_links
    ;;
  --doctor)
    if same_install && clean_old_links --check; then echo "project-docs-diagram is installed → $TARGET"; else
      echo "project-docs-diagram is not cleanly linked to this checkout: $TARGET" >&2; exit 1
    fi
    ;;
  --uninstall)
    if same_install; then rm "$TARGET"; echo "Uninstalled project-docs-diagram → $TARGET"
    elif [[ -e "$TARGET" || -L "$TARGET" ]]; then
      echo "Error: refusing to remove unrelated path: $TARGET" >&2; exit 1
    else
      echo "project-docs-diagram is not installed at $TARGET"
    fi
    clean_old_links
    ;;
  --help|-h)
    echo "Usage: bash install-arch.sh [--install|--doctor|--uninstall]"
    ;;
  *)
    echo "Usage: bash install-arch.sh [--install|--doctor|--uninstall]" >&2; exit 2
    ;;
esac
