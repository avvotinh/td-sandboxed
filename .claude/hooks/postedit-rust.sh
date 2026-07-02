#!/usr/bin/env bash
# PostToolUse hook (Edit|MultiEdit|Write): cargo fmt --check for edited .rs files.
# Walks UP from the edited file to the nearest Cargo.toml (does not assume the
# file lives directly under services/mt5-bridge).
#
# Assumption: neither `jq` nor a working `python`/`python3` is reliably present
# on PATH in this environment (Windows + Git Bash; the `python`/`python3` shims
# resolve to Microsoft Store stubs). `node` IS reliably present (ships with
# Claude Code's npm install), so it is used here to parse the hook JSON payload
# from stdin instead of jq/python.
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
  *.rs) ;;
  *) exit 0 ;;
esac

[ -f "$FILE" ] || exit 0

DIR="$(dirname -- "$FILE")"
CRATE_DIR=""
D="$DIR"
while [ -n "$D" ] && [ "$D" != "/" ] && [ "$D" != "." ]; do
  if [ -f "$D/Cargo.toml" ]; then
    CRATE_DIR="$D"
    break
  fi
  PARENT="$(dirname -- "$D")"
  if [ "$PARENT" = "$D" ]; then
    break
  fi
  D="$PARENT"
done

if [ -z "$CRATE_DIR" ]; then
  echo "postedit-rust hook: no Cargo.toml found above $FILE, skipping cargo fmt --check" >&2
  exit 0
fi

( cd "$CRATE_DIR" && cargo fmt --check 2>&1 | head -n 20 )
exit 0
