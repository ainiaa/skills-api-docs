#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
CODEX_SKILLS_DIR="${CODEX_HOME:-${HOME}/.codex}/skills"
CLAUDE_SKILLS_DIR="${CLAUDE_HOME:-${HOME}/.claude}/skills"
PYTHON_BIN="${UNDERSTAND_PYTHON:-python3}"
RENDERER_HOME="${UNDERSTAND_RENDERER_HOME:-${HOME}/.local/share/understand-skills/renderers}"
SKILL_NAMES=(understand-docs understand-arch understand-project)
SOURCES=("$SOURCE_DIR" "$SOURCE_DIR/skills/understand-arch" "$SOURCE_DIR/skills/understand-project")
OLD_NAMES=(api-savior-docs understand-api-docs understand-api-arch)
OLD_SOURCES=("$SOURCE_DIR" "$SOURCE_DIR" "$SOURCE_DIR/skills/understand-api-arch")
ACTION=install
HOST=both
NO_ENGINES=false
ENGINES=()

usage() {
  cat <<'EOF'
Understand skill group installer

Usage:
  bash install.sh [--host codex|claude|both] [--engine NAME ... | --no-engines]
  bash install.sh --doctor [--host codex|claude|both] [--engine NAME ... | --no-engines]
  bash install.sh --uninstall [--host codex|claude|both]

Default: install all three skills for Codex and Claude Code, and install all missing
Mermaid, PlantUML, draw.io, and Archify renderers. --engine installs/checks only
the named renderer; --no-engines installs/checks only the skill links.
Uninstall removes this checkout's skill links, never shared renderer programs.
EOF
}

same_install() {
  local target="$1" source="$2" resolved
  [[ -L "$target" ]] || return 1
  resolved="$(cd "$target" 2>/dev/null && pwd -P)" || return 1
  [[ "$resolved" == "$source" ]]
}

old_install() {
  local target="$1" source="$2"
  [[ -L "$target" && "$(readlink "$target")" == "$source" ]]
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install) ACTION=install; shift ;;
    --doctor) ACTION=doctor; shift ;;
    --uninstall) ACTION=uninstall; shift ;;
    --host)
      [[ $# -ge 2 && "$2" =~ ^(codex|claude|both)$ ]] || { usage >&2; exit 2; }
      HOST="$2"; shift 2 ;;
    --engine)
      [[ $# -ge 2 && "$2" =~ ^(mermaid|plantuml|drawio|archify)$ ]] || { usage >&2; exit 2; }
      ENGINES+=("$2"); shift 2 ;;
    --no-engines) NO_ENGINES=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

if [[ "$NO_ENGINES" == true && ${#ENGINES[@]} -gt 0 ]]; then
  echo "Error: --engine and --no-engines cannot be combined" >&2
  exit 2
fi
if [[ "$ACTION" == uninstall && ${#ENGINES[@]} -gt 0 ]]; then
  echo "Error: --engine does not apply to --uninstall" >&2
  exit 2
fi

SKILLS_DIRS=()
if [[ "$HOST" == codex || "$HOST" == both ]]; then SKILLS_DIRS+=("$CODEX_SKILLS_DIR"); fi
if [[ "$HOST" == claude || "$HOST" == both ]]; then SKILLS_DIRS+=("$CLAUDE_SKILLS_DIR"); fi

if [[ "$ACTION" == install ]]; then
  if [[ ! -f "$SOURCE_DIR/SKILL.md" || ! -f "$SOURCE_DIR/VERSION" ||
        ! -f "$SOURCE_DIR/scripts/generate_api_docs.py" ||
        ! -f "${SOURCES[1]}/SKILL.md" ||
        ! -f "${SOURCES[2]}/SKILL.md" ||
        ! -f "${SOURCES[2]}/assets/project-overview.md" ||
        ! -f "${SOURCES[2]}/assets/feature-description.md" ||
        ! -f "${SOURCES[2]}/assets/developer-guide.md" ||
        ! -f "$SOURCE_DIR/scripts/validate_project_doc.py" ||
        ! -f "$SOURCE_DIR/scripts/project_doc_context.py" ||
        ! -f "$SOURCE_DIR/scripts/project_doc_impact.py" ||
        ! -f "$SOURCE_DIR/scripts/generate_architecture.py" ]]; then
    echo "Error: incomplete skill group checkout: $SOURCE_DIR" >&2
    exit 1
  fi
  if ! command -v "$PYTHON_BIN" >/dev/null 2>&1 ||
     ! "$PYTHON_BIN" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
    echo "Error: Python 3.11 or newer is required (set UNDERSTAND_PYTHON to its executable)" >&2
    exit 1
  fi
fi

# Check every selected host before installing engines or changing any skill link.
if [[ "$ACTION" != doctor ]]; then
  for skills_dir in "${SKILLS_DIRS[@]}"; do
    for index in "${!SKILL_NAMES[@]}"; do
      target="$skills_dir/${SKILL_NAMES[$index]}"
      if ! same_install "$target" "${SOURCES[$index]}" && [[ -e "$target" || -L "$target" ]]; then
        echo "Error: refusing to replace unrelated path: $target" >&2
        exit 1
      fi
    done
  done
fi

renderer_args=()
if [[ ${#ENGINES[@]} -gt 0 ]]; then
  for engine in "${ENGINES[@]}"; do renderer_args+=(--engine "$engine"); done
fi
if [[ "$ACTION" != uninstall && "$NO_ENGINES" == false ]]; then
  if [[ "$ACTION" == doctor ]]; then renderer_args+=(--doctor); fi
  if [[ ${#renderer_args[@]} -gt 0 ]]; then
    "$PYTHON_BIN" "$SOURCE_DIR/scripts/install_renderers.py" "${renderer_args[@]}"
  else
    "$PYTHON_BIN" "$SOURCE_DIR/scripts/install_renderers.py"
  fi
fi

case "$ACTION" in
  install)
    if [[ "$NO_ENGINES" == true ]]; then
      mkdir -p "$RENDERER_HOME"
      : > "$RENDERER_HOME/no-auto-install"
    else
      rm -f "$RENDERER_HOME/no-auto-install"
    fi
    for skills_dir in "${SKILLS_DIRS[@]}"; do
      mkdir -p "$skills_dir"
      for index in "${!SKILL_NAMES[@]}"; do
        target="$skills_dir/${SKILL_NAMES[$index]}"
        if same_install "$target" "${SOURCES[$index]}"; then
          echo "${SKILL_NAMES[$index]} is already installed → $target"
        else
          ln -s "${SOURCES[$index]}" "$target"
          echo "Installed ${SKILL_NAMES[$index]} → $target"
        fi
      done
      for index in "${!OLD_NAMES[@]}"; do
        target="$skills_dir/${OLD_NAMES[$index]}"
        if old_install "$target" "${OLD_SOURCES[$index]}"; then
          rm "$target"
          echo "Removed old skill link → $target"
        fi
      done
    done
    ;;
  doctor)
    status=0
    version="$(head -1 "$SOURCE_DIR/VERSION" 2>/dev/null || true)"
    for skills_dir in "${SKILLS_DIRS[@]}"; do
      for index in "${!SKILL_NAMES[@]}"; do
        target="$skills_dir/${SKILL_NAMES[$index]}"
        if same_install "$target" "${SOURCES[$index]}"; then
          echo "${SKILL_NAMES[$index]} ${version} is installed → $target"
        else
          echo "${SKILL_NAMES[$index]} is not linked to this checkout: $target" >&2
          status=1
        fi
      done
      for index in "${!OLD_NAMES[@]}"; do
        target="$skills_dir/${OLD_NAMES[$index]}"
        if old_install "$target" "${OLD_SOURCES[$index]}"; then
          echo "Old skill link still installed: $target" >&2
          status=1
        fi
      done
    done
    exit "$status"
    ;;
  uninstall)
    for skills_dir in "${SKILLS_DIRS[@]}"; do
      for index in "${!SKILL_NAMES[@]}"; do
        target="$skills_dir/${SKILL_NAMES[$index]}"
        if same_install "$target" "${SOURCES[$index]}"; then
          rm "$target"
          echo "Uninstalled ${SKILL_NAMES[$index]} → $target"
        else
          echo "${SKILL_NAMES[$index]} is not installed at $target"
        fi
      done
      for index in "${!OLD_NAMES[@]}"; do
        target="$skills_dir/${OLD_NAMES[$index]}"
        if old_install "$target" "${OLD_SOURCES[$index]}"; then
          rm "$target"
          echo "Removed old skill link → $target"
        fi
      done
    done
    ;;
esac
