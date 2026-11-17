#!/usr/bin/env bash
# Repo hygiene guard: exits non-zero if any guarded path is tracked by git.
#
# The list of guarded paths arrives via the GUARD_NAMES environment variable
# (newline-separated; on CI it is set from the GUARDED_PATHS repo secret, so
# this script reveals nothing about what is guarded). Local developers keep
# the same list in .git/info/exclude.
#
# Entries may be:
#   - an exact file path        docs/build-plan-fa.md
#   - a directory (trailing /)  docs/notes/
#   - a glob-ish prefix         eval/data*
# Every entry is matched as a fixed-string path prefix: a tracked file is a
# violation if it equals the entry or lives inside it. Fixed-string compare
# (awk index(), not regex) so no character in the list can change the meaning.
set -u

if [ -z "${GUARD_NAMES:-}" ]; then
  echo "::error::GUARD_NAMES is empty. Set the GUARDED_PATHS secret (repo"
  echo "  Settings → Secrets and variables → Actions) to a newline-separated"
  echo "  list of paths that must never be committed."
  exit 1
fi

tracked="$(git ls-files)"
violations=0

while IFS= read -r name; do
  name="${name%$'\r'}"          # tolerate CRLF in the secret
  [ -z "$name" ] && continue
  prefix="${name%/}"            # docs/notes/ -> docs/notes
  prefix="${prefix%\*}"         # eval/data*  -> eval/data
  hits="$(printf '%s\n' "$tracked" | awk -v p="$prefix" '
      index($0, p) == 1 &&
      (length($0) == length(p) || substr($0, length(p) + 1, 1) == "/") { print }')"
  if [ -n "$hits" ]; then
    echo "::error::A file that must never be committed is tracked by git. Offending path(s):"
    printf '%s\n' "$hits"
    violations=1
  fi
done <<EOF
$GUARD_NAMES
EOF

if [ "$violations" -ne 0 ]; then
  echo "Fix: git rm --cached <path> (keep the working-tree file); never rewrite history."
  exit 1
fi
echo "hygiene: clean — no guarded path is tracked ($(printf '%s\n' "$tracked" | wc -l) tracked files checked)"
