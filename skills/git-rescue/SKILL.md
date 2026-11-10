---
name: git-rescue
description: Get a git repository out of trouble and do everyday git tasks safely. Use when the user is stuck in a merge, rebase or conflict, lost commits or changes, committed to the wrong branch, wants to undo something in git, or asks how to do a git operation.
---

# Git rescue

Almost nothing committed is ever truly lost in git. The danger is in the fix, so look first.

## First, see the state

If you can run commands:

```
bash scripts/git_overview.sh /path/to/repo
```

It prints, without changing anything: branch and upstream distance, any operation in progress (merge, rebase, cherry-pick, bisect) with its abort command, changed and conflicted files, stashes, recent commits and the reflog.

Otherwise ask the user for the output of `git status` and `git log --oneline -10`.

## Rules

- **Make a safety net before anything destructive**: `git branch backup-before-fix`. It costs nothing.
- **Ask whether the commits were pushed.** Rewriting pushed history (`rebase`, `commit --amend`, `reset`) breaks things for others; prefer `git revert` there.
- **Never suggest** `git push --force` on a shared branch, `git reset --hard` or `git clean -fd` with uncommitted work, or `git checkout .`, without stating exactly what will be destroyed. Use `--force-with-lease` when force is truly needed.
- Give one command at a time for risky steps, and say what the user should see afterwards.

## Common situations

| Situation | Fix |
|---|---|
| Undo last commit, keep the changes | `git reset --soft HEAD~1` |
| Undo a pushed commit | `git revert <sha>` |
| Fix the last commit message (not pushed) | `git commit --amend` |
| Committed on the wrong branch | `git branch right-branch` then `git reset --hard HEAD~1`, then `git switch right-branch` |
| Lost commits after reset or rebase | `git reflog`, find the sha, `git branch rescue <sha>` |
| Deleted a branch | `git reflog` to find its last sha, `git branch name <sha>` |
| Stuck in a rebase or merge | `git rebase --abort` or `git merge --abort` returns to before it started |
| Discard changes in one file | `git restore <file>` (uncommitted changes are gone for good) |
| Unstage a file | `git restore --staged <file>` |
| Park work in progress | `git stash push -m "what"`; back with `git stash pop` |
| Remove a file from git but keep it on disk | `git rm --cached <file>` and add it to `.gitignore` |
| Committed a secret | Rotate the secret first. Removing it from history does not un-leak it. |

## Resolving conflicts

1. `git status` lists the conflicted files.
2. In each, the part between `<<<<<<<` and `=======` is yours, between `=======` and `>>>>>>>` is theirs. Edit to the wanted result and delete all three marker lines.
3. `git add <file>` for each, then `git rebase --continue` or `git commit`.
4. Run the tests before pushing. A conflict resolved textually can still be broken logically.

## Answer format

What state the repository is in, the exact commands in order, what each does, and what cannot be undone.
