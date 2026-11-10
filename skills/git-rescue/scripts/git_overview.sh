#!/usr/bin/env bash
# Print the state of a git repository in one screen, without changing anything.
# Usage: git_overview.sh [path]
set -euo pipefail
cd "${1:-.}"
git rev-parse --git-dir >/dev/null 2>&1 || { echo "not a git repository: $(pwd)"; exit 1; }

gitdir=$(git rev-parse --git-dir)
echo "== branch =="
branch=$(git symbolic-ref --short -q HEAD || echo "DETACHED at $(git rev-parse --short HEAD 2>/dev/null || echo 'no commits')")
echo "$branch"
if upstream=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null); then
  read -r behind ahead < <(git rev-list --left-right --count "$upstream"...HEAD)
  echo "upstream $upstream: $ahead ahead, $behind behind"
else
  echo "no upstream set"
fi

echo; echo "== operation in progress =="
state=none
[ -d "$gitdir/rebase-merge" ] || [ -d "$gitdir/rebase-apply" ] && state="rebase (continue: git rebase --continue, abort: git rebase --abort)"
[ -f "$gitdir/MERGE_HEAD" ] && state="merge (abort: git merge --abort)"
[ -f "$gitdir/CHERRY_PICK_HEAD" ] && state="cherry-pick (abort: git cherry-pick --abort)"
[ -f "$gitdir/REVERT_HEAD" ] && state="revert (abort: git revert --abort)"
[ -f "$gitdir/BISECT_LOG" ] && state="bisect (stop: git bisect reset)"
echo "$state"

echo; echo "== working tree =="
git status --short | head -40
[ -z "$(git status --short)" ] && echo "clean"
conflicts=$(git diff --name-only --diff-filter=U 2>/dev/null || true)
[ -n "$conflicts" ] && { echo; echo "conflicted files:"; echo "$conflicts"; }

echo; echo "== stashes =="
git stash list | head -5
[ -z "$(git stash list)" ] && echo "none"

echo; echo "== last commits =="
git log --oneline --decorate -8 2>/dev/null || echo "no commits yet"

echo; echo "== recent HEAD movements (reflog; lost commits can be recovered from here) =="
git reflog -8 --format='%h %gd %gs' 2>/dev/null || true
