#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd -P -- "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
CODEX_SKILLS_DIR="${CODEX_HOME:-${HOME}/.codex}/skills"
CLAUDE_SKILLS_DIR="${CLAUDE_HOME:-${HOME}/.claude}/skills"
ZCODE_SKILLS_DIR="${HOME}/.zcode/skills"
DSH_SKILLS_DIR="${HOME}/.dsh/skills"
if [[ "${DSH_HOME:-}" =~ [^[:space:]] ]]; then DSH_SKILLS_DIR="$DSH_HOME/skills"; fi
case "$DSH_SKILLS_DIR" in
  "~/"*|"~\\"*) DSH_SKILLS_DIR="$HOME/${DSH_SKILLS_DIR:2}" ;;
esac
GEMINI_SKILLS_DIR="${GEMINI_CLI_HOME:-${HOME}}/.gemini/skills"
GROK_SKILLS_DIR="${GROK_HOME:-${HOME}/.grok}/skills"
PI_SKILLS_DIR="${PI_CODING_AGENT_DIR:-${HOME}/.pi/agent}/skills"
case "$PI_SKILLS_DIR" in
  "~/"*) PI_SKILLS_DIR="$HOME/${PI_SKILLS_DIR#\~/}" ;;
esac
OPENCODE_SKILLS_DIR="${HOME}/.config/opencode/skills"
if [[ "${XDG_CONFIG_HOME:-}" == /* ]]; then OPENCODE_SKILLS_DIR="$XDG_CONFIG_HOME/opencode/skills"; fi
PYTHON_BIN="${UNDERSTAND_PYTHON:-python3}"
RENDERER_HOME="${UNDERSTAND_RENDERER_HOME:-${HOME}/.local/share/understand-skills/renderers}"
SKILL_NAMES=(project-docs project-docs-api project-docs-diagram project-docs-overview)
SOURCES=("$SOURCE_DIR/skills/project-docs" "$SOURCE_DIR/skills/project-docs-api"
         "$SOURCE_DIR/skills/project-docs-diagram" "$SOURCE_DIR/skills/project-docs-overview")
OLD_NAMES=(api-savior-docs understand-api-docs understand-api-arch understand-docs understand-arch understand-project)
OLD_SOURCES=("$SOURCE_DIR" "$SOURCE_DIR" "$SOURCE_DIR/skills/understand-api-arch"
             "$SOURCE_DIR" "$SOURCE_DIR/skills/understand-arch" "$SOURCE_DIR/skills/understand-project")
ACTION=install
ACTION_COUNT=0
UPDATE_DEPS=false
HOST=both
NO_ENGINES=false
ENGINES=()

usage() {
  cat <<'EOF'
Project Docs skill collection installer

Usage:
  bash install.sh [--host HOST] [--engine NAME ... | --no-engines]
  bash install.sh --doctor [--host HOST] [--engine NAME ... | --no-engines]
  bash install.sh --uninstall [--host HOST]
  bash install.sh --update [--host HOST] [--engine NAME ... | --no-engines]
  bash install.sh --update-deps [--host HOST] [--engine NAME ... | --no-engines]

HOST: codex, claude, zcode, dsh, gemini, grok, pi, opencode, both, all.
both (default) selects Codex and Claude Code; all selects all eight hosts.
grok targets xAI Grok Build; pi targets the pi coding agent.

Default: install the unified entry and three specialist skills for Codex and Claude Code, and install all missing
Mermaid, PlantUML, draw.io, and Archify renderers. --engine installs/checks only
the named renderer; --no-engines installs/checks only the skill links.
Uninstall removes this checkout's skill links, never shared renderer programs.
--update fast-forwards the current tracked branch, then synchronizes the skills
and pinned renderer versions. --update-deps skips the Git update.
EOF
}

same_install() {
  local target="$1" source="$2" resolved
  [[ -L "$target" ]] || return 1
  resolved="$(cd -P -- "$target" 2>/dev/null && pwd -P)" || return 1
  [[ "$resolved" == "$source" ]]
}

old_install() {
  local target="$1" source="$2" link parent suffix
  [[ -L "$target" ]] || return 1
  link="$(readlink "$target")"
  [[ "$link" == /* ]] || link="$(dirname "$target")/$link"
  # Resolve existing ancestors so owned links remain removable after source loss.
  parent="$(dirname "$link")"
  suffix="$(basename "$link")"
  while [[ ! -e "$parent" && ! -L "$parent" ]]; do
    suffix="$(basename "$parent")/$suffix"
    parent="$(dirname "$parent")"
  done
  parent="$(cd -P -- "$parent" 2>/dev/null && pwd -P)" || return 1
  [[ "$parent/$suffix" == "$source" ]]
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install) ACTION=install; ACTION_COUNT=$((ACTION_COUNT + 1)); shift ;;
    --doctor) ACTION=doctor; ACTION_COUNT=$((ACTION_COUNT + 1)); shift ;;
    --uninstall) ACTION=uninstall; ACTION_COUNT=$((ACTION_COUNT + 1)); shift ;;
    --update) ACTION=update; ACTION_COUNT=$((ACTION_COUNT + 1)); shift ;;
    --update-deps) UPDATE_DEPS=true; ACTION_COUNT=$((ACTION_COUNT + 1)); shift ;;
    --host)
      [[ $# -ge 2 && "$2" =~ ^(codex|claude|zcode|dsh|gemini|grok|pi|opencode|both|all)$ ]] || { usage >&2; exit 2; }
      HOST="$2"; shift 2 ;;
    --engine)
      [[ $# -ge 2 && "$2" =~ ^(mermaid|plantuml|drawio|archify)$ ]] || { usage >&2; exit 2; }
      ENGINES+=("$2"); shift 2 ;;
    --no-engines) NO_ENGINES=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

if [[ "$ACTION_COUNT" -gt 1 ]]; then
  echo "Error: choose only one install, doctor, uninstall, or update action" >&2
  exit 2
fi
if [[ "$NO_ENGINES" == true && ${#ENGINES[@]} -gt 0 ]]; then
  echo "Error: --engine and --no-engines cannot be combined" >&2
  exit 2
fi
if [[ "$ACTION" == uninstall && ${#ENGINES[@]} -gt 0 ]]; then
  echo "Error: --engine does not apply to --uninstall" >&2
  exit 2
fi

SKILLS_DIRS=()
if [[ "$HOST" == codex || "$HOST" == both || "$HOST" == all ]]; then SKILLS_DIRS+=("$CODEX_SKILLS_DIR"); fi
if [[ "$HOST" == claude || "$HOST" == both || "$HOST" == all ]]; then SKILLS_DIRS+=("$CLAUDE_SKILLS_DIR"); fi
if [[ "$HOST" == zcode || "$HOST" == all ]]; then SKILLS_DIRS+=("$ZCODE_SKILLS_DIR"); fi
if [[ "$HOST" == dsh || "$HOST" == all ]]; then SKILLS_DIRS+=("$DSH_SKILLS_DIR"); fi
if [[ "$HOST" == gemini || "$HOST" == all ]]; then SKILLS_DIRS+=("$GEMINI_SKILLS_DIR"); fi
if [[ "$HOST" == grok || "$HOST" == all ]]; then SKILLS_DIRS+=("$GROK_SKILLS_DIR"); fi
if [[ "$HOST" == pi || "$HOST" == all ]]; then SKILLS_DIRS+=("$PI_SKILLS_DIR"); fi
if [[ "$HOST" == opencode || "$HOST" == all ]]; then SKILLS_DIRS+=("$OPENCODE_SKILLS_DIR"); fi

if [[ "$ACTION" == install || "$ACTION" == update ]]; then
  if ! command -v "$PYTHON_BIN" >/dev/null 2>&1 ||
     ! "$PYTHON_BIN" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
    echo "Error: Python 3.11 or newer is required (set UNDERSTAND_PYTHON to its executable)" >&2
    exit 1
  fi
fi

if [[ "$ACTION" == install ]]; then
  for source in "${SOURCES[@]}"; do
    if [[ ! -f "$source/SKILL.md" ]]; then
      echo "Error: incomplete skill collection checkout: $source" >&2
      exit 1
    fi
  done
  if [[ ! -f "$SOURCE_DIR/VERSION" ||
        ! -f "$SOURCE_DIR/scripts/generate_api_docs.py" ||
        ! -f "${SOURCES[3]}/assets/project-overview.md" ||
        ! -f "${SOURCES[3]}/assets/feature-description.md" ||
        ! -f "${SOURCES[3]}/assets/developer-guide.md" ||
        ! -f "${SOURCES[3]}/assets/architecture-overview.md" ||
        ! -f "$SOURCE_DIR/scripts/validate_project_doc.py" ||
        ! -f "$SOURCE_DIR/scripts/project_doc_context.py" ||
        ! -f "$SOURCE_DIR/scripts/project_doc_impact.py" ||
        ! -f "$SOURCE_DIR/scripts/generate_architecture.py" ]]; then
    echo "Error: incomplete skill group checkout: $SOURCE_DIR" >&2
    exit 1
  fi
fi

# Check every selected host before installing engines or changing any skill link.
if [[ "$ACTION" != doctor ]]; then
  for skills_dir in "${SKILLS_DIRS[@]}"; do
    ancestor="$skills_dir"
    while [[ ! -e "$ancestor" && ! -L "$ancestor" ]]; do
      ancestor="$(dirname "$ancestor")"
    done
    if [[ ! -d "$ancestor" ]]; then
      echo "Error: not a usable skill directory: $ancestor (for $skills_dir)" >&2
      exit 1
    fi
    for index in "${!SKILL_NAMES[@]}"; do
      target="$skills_dir/${SKILL_NAMES[$index]}"
      if ! same_install "$target" "${SOURCES[$index]}" &&
         ! old_install "$target" "${SOURCES[$index]}" && [[ -e "$target" || -L "$target" ]]; then
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
if [[ "$ACTION" == update ]]; then
  update_args=(--host "$HOST")
  if [[ "$NO_ENGINES" == true ]]; then update_args+=(--no-engines); fi
  if [[ ${#ENGINES[@]} -gt 0 ]]; then update_args+=("${renderer_args[@]}"); fi
  exec "$PYTHON_BIN" "$SOURCE_DIR/scripts/update_project_docs.py" "${update_args[@]}"
fi
renderer_status=0
if [[ "$ACTION" != uninstall && "$NO_ENGINES" == false ]]; then
  if [[ "$ACTION" == doctor ]]; then renderer_args+=(--doctor); fi
  if [[ "$UPDATE_DEPS" == true ]]; then renderer_args+=(--update); fi
  if [[ "$ACTION" == doctor ]]; then
    "$PYTHON_BIN" "$SOURCE_DIR/scripts/install_renderers.py" "${renderer_args[@]}" || renderer_status=1
  elif [[ ${#renderer_args[@]} -gt 0 ]]; then
    "$PYTHON_BIN" "$SOURCE_DIR/scripts/install_renderers.py" "${renderer_args[@]}"
  else
    "$PYTHON_BIN" "$SOURCE_DIR/scripts/install_renderers.py"
  fi
fi

case "$ACTION" in
  install)
    if [[ "$NO_ENGINES" == true ]]; then
      if [[ "$UPDATE_DEPS" == false ]]; then
        mkdir -p "$RENDERER_HOME"
        : > "$RENDERER_HOME/no-auto-install"
      fi
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
    status="$renderer_status"
    version="$(head -1 "$SOURCE_DIR/VERSION" 2>/dev/null || true)"
    if [[ -z "$version" ]]; then
      echo "Missing or empty collection VERSION: $SOURCE_DIR/VERSION" >&2
      status=1
    fi
    for skills_dir in "${SKILLS_DIRS[@]}"; do
      for index in "${!SKILL_NAMES[@]}"; do
        target="$skills_dir/${SKILL_NAMES[$index]}"
        if same_install "$target" "${SOURCES[$index]}"; then
          if [[ -f "$target/SKILL.md" && -r "$target/SKILL.md" && -s "$target/SKILL.md" ]]; then
            echo "${SKILL_NAMES[$index]} ${version} is installed → $target"
          else
            echo "Missing, empty, or unreadable skill entry: $target/SKILL.md" >&2
            status=1
          fi
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
        if same_install "$target" "${SOURCES[$index]}" || old_install "$target" "${SOURCES[$index]}"; then
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
