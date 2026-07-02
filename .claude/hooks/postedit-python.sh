#!/usr/bin/env bash
# PostToolUse hook (Edit|MultiEdit|Write): ruff check for edited .py files.
#
# Assumption: neither `jq` nor a working `python`/`python3` is reliably present
# on PATH in this environment (Windows + Git Bash; the `python`/`python3` shims
# resolve to Microsoft Store stubs). `node` IS reliably present (ships with
# Claude Code's npm install), so it is used here to parse the hook JSON payload
# from stdin instead of jq/python.
#
# Assumption: hooks run with cwd == repo root (same as the Bash tool's cwd).
set -u

INPUT="$(cat)"
FILE="$(printf '%s' "$INPUT" | node -e '
let d = "";
process.stdin.on("data", c => d += c);
process.stdin.on("end", () => {
  try {
    const j = JSON.parse(d);
    process.stdout.write((j.tool_input && j.tool_input.file_path) || "");
  } catch (e) {}
});
')"

# Normalize Windows backslashes to forward slashes for reliable matching under Git Bash.
FILE="$(printf '%s' "$FILE" | tr '\' '/' 2>/dev/null)"

case "$FILE" in
  *.py) ;;
  *) exit 0 ;;
esac

[ -f "$FILE" ] || exit 0

REPO_ROOT="$(pwd)"

case "$FILE" in
  *services/*)
    AFTER="${FILE#*services/}"
    SVC="${AFTER%%/*}"
    REL="${AFTER#*/}"
    SVC_DIR="$REPO_ROOT/services/$SVC"
    if [ -d "$SVC_DIR" ] && [ -f "$SVC_DIR/pyproject.toml" ]; then
      ( cd "$SVC_DIR" && uv run ruff check -- "$REL" 2>&1 | head -n 20 )
    else
      ( cd "$REPO_ROOT" && ruff check -- "$FILE" 2>&1 | head -n 20 )
    fi
    ;;
  *)
    ( cd "$REPO_ROOT" && ruff check -- "$FILE" 2>&1 | head -n 20 )
    ;;
esac
exit 0
