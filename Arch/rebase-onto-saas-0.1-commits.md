# Rebase `composable-pipeline-v3` onto `saas-0.1-commits`

## Context

The current feature branch `composable-pipeline-v3` was forked from `main` at commit `6449e64b` (March 31, 2026). Since then:

- **Feature branch:** 28 commits, 183 files changed, +19,555 lines. Major work: composable ingestion/retrieval pipelines, Ray → Redis+KEDA execution backend, Helm chart, Terraform, docling-serve support, NDJSON streaming.
- **Stable branch (`origin/saas-0.1-commits`):** 107 commits, 199 files changed. This is the current stable release; the goal is to keep building features on top of it rather than letting the feature branch drift.

We want the feature branch rebased onto stable so future work continues from the latest released code.

**16 files overlap** between the two changesets and will conflict, the heaviest being `pyproject.toml`, `uv.lock`, `docker-compose.yml`, `src/main.py`, `src/api/chat.py`, `src/api/v1/chat.py`, `src/config/settings.py`, `src/dependencies.py`.

## Recommended approach: backup + interactive rebase with `rerere`

A straight `git rebase` of all 28 commits is feasible but painful — `uv.lock` and `pyproject.toml` will conflict repeatedly across many commits. Squashing first reduces the work to one conflict-resolution session at the cost of losing per-commit granularity. We preserve full history on a backup tag so nothing is lost either way.

### Step 1 — Safety net

```bash
git fetch origin
git tag backup/composable-pipeline-v3-pre-rebase composable-pipeline-v3
git push origin backup/composable-pipeline-v3-pre-rebase   # off-machine backup
git config rerere.enabled true                              # remember conflict resolutions
```

### Step 2 — Choose rebase strategy

Pick one of:

**(A) Preserve all 28 commits (linear history, more conflict passes)**
```bash
git checkout composable-pipeline-v3
git rebase origin/saas-0.1-commits
# resolve conflicts per commit; rerere will replay matching resolutions
# for uv.lock conflicts: `git checkout --theirs uv.lock && uv lock` then `git add uv.lock`
```

**(B) Squash to one commit, then rebase (one conflict pass, loses granularity)**
```bash
git checkout -b composable-pipeline-v3-squashed composable-pipeline-v3
git reset --soft $(git merge-base composable-pipeline-v3 origin/saas-0.1-commits)
git commit -m "Composable pipeline v3 (squashed)"
git rebase origin/saas-0.1-commits
# one conflict-resolution session
```

Recommend **(B)** unless the per-commit history is needed for review or bisect — the time saved is significant given the 19K-line feature delta touching the same dependency manifests stable also moved.

### Step 3 — Conflict resolution guidance

For overlapping files, the merge bias should usually be:

| File | Bias | Why |
|---|---|---|
| `pyproject.toml` | merge both | Stable adds prod deps (litellm, agentd, fastmcp); feature adds pipeline deps (langchain, redis, deepagents). Both needed. |
| `uv.lock` | regenerate | Take `--theirs` (stable), then `uv lock` to re-resolve with merged `pyproject.toml`. |
| `src/main.py`, `src/api/*`, `src/config/settings.py`, `src/dependencies.py` | per-hunk inspection | Feature branch's composable-pipeline integration must coexist with stable's bug fixes. |
| `docker-compose.yml` | per-hunk inspection | Both branches likely added services. |
| `src/models/processors.py`, `src/api/connector_router.py`, `src/api/settings.py` | per-hunk | Both touched but in different sections — usually mergeable. |

### Step 4 — Verify before replacing the branch

```bash
# Smoke checks on the rebased branch
uv sync                                  # deps resolve
uv run pytest tests/ -x                  # tests still pass
docker compose config -q                 # compose file is valid
helm lint charts/openrag                 # helm chart valid
```

If approach (B) was used and verification passes, fast-forward the original branch:
```bash
git checkout composable-pipeline-v3
git reset --hard composable-pipeline-v3-squashed
```

### Step 5 — Force-push (with care)

```bash
git push --force-with-lease origin composable-pipeline-v3
```

`--force-with-lease` (not `--force`) refuses the push if the remote moved unexpectedly, protecting against overwriting a teammate's work.

## Critical files to inspect during conflict resolution

- `pyproject.toml` — both branches restructured the dependencies block
- `uv.lock` — regenerate, don't hand-merge
- `src/main.py` — app bootstrap, both branches modified
- `src/api/chat.py`, `src/api/v1/chat.py` — feature branch added NDJSON streaming; stable likely has fixes
- `src/config/settings.py` — feature added DISABLE_LANGFLOW + composable mode flags
- `src/dependencies.py` — feature lazy-loads PipelineService
- `docker-compose.yml` — feature added Redis/KEDA services

## Verification end-to-end

After rebase + verification scripts above, additionally:

1. Boot stack locally: `docker compose up -d` and confirm `http://localhost:8000/health` is 200.
2. Run a smoke ingestion against composable mode: `DISABLE_LANGFLOW=1 uv run openrag-ingest <test-file>`.
3. Run a retrieval through the composable retrieval CLI: `uv run openrag-retrieve "<query>"`.
4. Hit the chat endpoint to confirm both streaming paths work.
5. If charts changed: `helm template charts/openrag | kubectl apply --dry-run=client -f -`.

## Rollback

If anything goes wrong:
```bash
git checkout composable-pipeline-v3
git reset --hard backup/composable-pipeline-v3-pre-rebase
git push --force-with-lease origin composable-pipeline-v3
```
