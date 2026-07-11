---
description: Bring all changes from main into the current branch (fetch + merge origin/main)
allowed-tools: Bash(git fetch:*), Bash(git merge:*), Bash(git status:*), Bash(git branch:*), Bash(git rev-list:*), Bash(git checkout:*), Bash(git diff:*), Bash(git add:*), Bash(git commit:*), Bash(git log:*)
---

Bring all changes from `main` into the branch currently checked out.

Steps:

1. Guard: if the current branch IS `main`, stop and report — there is nothing to sync into itself.
2. Run `git fetch origin main` to update the remote-tracking ref.
3. Report the divergence with `git rev-list --left-right --count HEAD...origin/main` (left = ahead, right = behind). If behind is 0, report "already up to date with main" and stop.
4. Merge with `git merge origin/main`.
5. If there are merge conflicts: resolve every conflicted file by taking **main's** version (`git checkout --theirs <file>` then `git add <file>`), then complete the merge with `git commit --no-edit`. This repo's rule is: on conflict, always respect main.
6. Report the result: new HEAD, files changed, and confirm the current branch now contains all of main.

Do NOT push. Leave the merge local unless the user explicitly asks to push.
