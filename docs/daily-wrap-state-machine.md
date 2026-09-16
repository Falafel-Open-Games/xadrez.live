# Daily Wrap State Machine

The daily wrap flow should be resumable and boring: rerunning it continues from
the last durable decision instead of reconstructing intent from stale source
files.

## Principles

- Raw exported files are inputs.
- Resolved workflow state is the source of truth after user prompts.
- Generated files are replaceable outputs.
- Every prompt records a decision before the next risky command runs.
- Every command can fail without losing previous decisions.
- Reruns continue unless `--restart` is explicitly requested.

## State File

Per-session workflow state lives in:

```text
data/fcz/workflows/NNNN.json
```

The state records:

- selected input source paths
- user decisions such as chat fallback and calibration anchor
- step statuses
- last command, exit code, and failure message when a step fails
- external prerequisites that are temporarily unavailable, including the last
  YouTube metadata retry and its reason

## Step Statuses

Steps use a small fixed vocabulary:

- `pending`: not started
- `running`: currently executing
- `done`: completed successfully
- `blocked`: needs user action or unavailable input
- `failed`: command failed and can be retried
- `skipped`: intentionally not run

## Initial Step List

The first implementation wraps existing tools instead of replacing all of them:

1. `inputs`
2. `chat`
3. `youtube_metadata`
4. `wrap_session`
5. `verify`
6. `build`

## External Prerequisites

Some wrapup inputs are eventually consistent or can fail transiently. YouTube
`release_timestamp` metadata, fetched through `yt-dlp`, is one of them. It is
required for trustworthy game and puzzle timeline timestamps, so the workflow
must not silently substitute the scheduled session time.

The target behavior is:

- retry metadata automatically whenever `just menu` resumes the session
- record whether the result was unavailable, transiently failed, or successful
- continue independent metadata/chat work when possible
- defer timeline-dependent work with a clear `blocked` or `waiting` status
- retry on the next run without requiring the user to remember a separate
  recovery command

Running `python3 scripts/update_youtube_video_metadata.py NNNN` remains a
useful diagnostic/manual retry, but it should not be required for the normal
daily flow.

Later refactors can split `wrap_session` into finer steps, such as
`resolve_toml`, `apply_page`, `merge_chat`, `calibrate`, `timeline`, and
`youtube_finish`.

The legacy wrapper now records coarse phase checkpoints in its existing
`data/fcz/wrap_sessions/NNNN.json` state under `phases`. These checkpoints are
an execution ledger. The metadata/chat checkpoint is now authoritative: when
it is complete, a resumed wrap reuses the already-applied page and chat replay
even if the original export files are no longer present.

The analysis/calibration checkpoint now behaves the same way, so later retries
do not repeat Lichess analysis, offset calibration, or timeline regeneration.

The YouTube finishing checkpoint now behaves the same way, so completed
editorial choices, chapter publication, thumbnail work, and final verification
are not repeated on a later retry.

The next-session and build checkpoints are also durable. A completed schedule,
an explicit decision not to schedule, and a completed build are all reused on
resume; `--restart` is required to intentionally revisit them.
