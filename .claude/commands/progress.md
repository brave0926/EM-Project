---
description: Sync PROGRESS.md with the repo, then show the Snapshot and the next 3 steps
---

Update PROGRESS.md following the Session protocol in CLAUDE.md (steps b, c, d).

1. Gather facts with commands, do not guess:
   - `git status`, `git log --oneline -10`, `git tag`, ahead/behind origin (`git fetch -q` then `git rev-list --left-right --count origin/main...HEAD`)
   - `uv run pytest -q` (test count and pass/fail)
   - the endpoint list from `backend/app/controllers/`
2. If PROGRESS.md and the repo disagree, trust the repo and fix PROGRESS.md.
3. Update PROGRESS.md:
   - Snapshot: date, branch, last commit (hash + message), pushed or ahead by N, test count, working tree clean or the list of uncommitted files.
   - Move every finished Next steps item to Done with its commit hash. Only mark it done if a passing test or a command output proves it; otherwise write "unverified".
   - Contracts and Endpoints tables: update any status or measured value that changed.
   - In progress / uncommitted: list half-done work with file names.
   - Add one Session log line at the top (newest first): date, what changed, commit hashes, what to do next.
   - Keep the file under ~150 lines: compress old Done items, move Session log lines beyond the last 10 into `docs/progress_archive.md`.
   - Never write keys, tokens, personal data or raw API responses.
4. Do not commit, push or tag unless I ask. If only PROGRESS.md changed, suggest the commit message `docs(progress): <summary> [W<current week>]`.
5. Show me the Snapshot section and the next 3 steps (IDs, goal, "done when").

$ARGUMENTS
