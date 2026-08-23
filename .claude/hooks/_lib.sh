#!/usr/bin/env bash
# Shared helpers for the hook scripts. No `set -e` anywhere in the hooks: exit
# codes are the hook contract (0 allow, 2 block).

# Claude can enter a linked worktree while CLAUDE_PROJECT_DIR stays at the
# launch root, so the checkout to act on comes from the payload's cwd.
hook_root() {
  local cwd=$1 root
  if [ -d "$cwd" ] && root=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null) && [ -n "$root" ]; then
    printf '%s' "$root"
  elif [ -d "$CLAUDE_PROJECT_DIR" ]; then
    printf '%s' "$CLAUDE_PROJECT_DIR"
  else
    return 1
  fi
}

# On Windows both sides are compared as long-form `C:/...` paths,
# case-insensitively, because cygpath maps TEMP to /tmp and short (8.3) names
# to different POSIX spellings of the same directory.
hook_relative_path() {
  local path=$1 root=$2 rel lpath lroot
  [ -n "$path" ] && [ -d "$root" ] || return 1
  if command -v cygpath >/dev/null 2>&1; then
    case "$path" in *..*) path=$(realpath -m "$(cygpath -u "$path")") ;; esac
    path=$(cygpath -ml "$path") && root=$(cygpath -ml "$root") || return 1
    lpath=${path,,}; lroot=${root,,}
    case "$lpath" in "$lroot"/*) rel=${path:$((${#root} + 1))} ;; *) return 1 ;; esac
  else
    path=${path//\\//}; root=${root//\\//}
    rel=$(realpath -m --relative-to="$root" "$path" 2>/dev/null) || return 1
    case "$rel" in ../*|..|/*) return 1 ;; esac
  fi
  [ -n "$rel" ] || return 1
  printf '%s' "$rel"
}
