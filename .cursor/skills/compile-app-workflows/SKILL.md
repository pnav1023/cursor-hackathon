---
name: compile-app-workflows
description: Compiles a product recording and OpenAPI spec into Cursor skills by POSTing to the local workflow-compiler FastAPI service. Use when the user asks to compile workflows, generate skills from a video or OpenAPI spec, upload an mp4 to the compiler, or run the intake compile job.
---

# Compile App Workflows

Turn a screen recording plus an API spec into one Cursor skill per workflow. Do **not** extract workflows or invent REST paths yourself. The FastAPI service does that.

## Service

Default base URL: `http://127.0.0.1:8000`

Override with `COMPILE_API_URL`. If `COMPILE_API_KEY` is set, send `Authorization: Bearer <key>`.

If `/health` is unreachable, start the service from the repo root:

```bash
PYTHONPATH=backend uvicorn workflow_compiler.service:app --reload --port 8000
```

## Inputs

Collect paths from the user. At least one of **video**, **video_url**, or **workflows JSON** is required. Spec-only is invalid (the API returns 400).

| Input | Form field | Notes |
| --- | --- | --- |
| Screen recording `.mp4` | `video` | Optional if workflows JSON is provided |
| OpenAPI YAML/JSON | `spec` | Needed to ground skills to real endpoints |
| Extra notes / docs | `docs` | Repeatable; appended to extract + map prompts |
| Pre-extracted workflows | `workflows` | Skip Gemini; still maps + emits skills |
| Remote video | `video_url` | Alternative to uploading `video` |

Prefer files in this repo when the user does not specify others:

- Video: `assets/openemr.mp4`
- Spec: `fixtures/openemr/openapi.yaml`
- Fast path (no Gemini): `fixtures/openemr/workflows.json`

## Run the job

From the repo root, execute the bundled client. It POSTs `multipart/form-data` to `POST /v1/jobs`, polls `GET /v1/jobs/{id}` until `status` is `done` or `failed`, then writes each returned skill to `--out`.

```bash
python .cursor/skills/compile-app-workflows/scripts/compile_job.py \
  --video assets/openemr.mp4 \
  --spec fixtures/openemr/openapi.yaml \
  --out .cursor/skills
```

Skip Gemini when workflows already exist:

```bash
python .cursor/skills/compile-app-workflows/scripts/compile_job.py \
  --workflows fixtures/openemr/workflows.json \
  --spec fixtures/openemr/openapi.yaml \
  --out .cursor/skills
```

Pass extra docs with repeated `--doc path`. Do not call Gemini or OpenAI from this skill. Do not `curl` invent endpoints.

Video jobs often take several minutes (`extract` then `map`). Poll output looks like `status=running stage=extract`. Keep waiting until the script exits.

## After success

1. Summarize `skill_count` and each written `.cursor/skills/<name>/SKILL.md`.
2. Call out skills whose body says they have **no matching operations** — those UI steps are out of spec on purpose.
3. Do not rewrite the generated markdown to add APIs. The mapper already dropped anything not in the spec.

## Failures

- Health check failed → start uvicorn, then retry.
- HTTP 400 "Provide a video file..." → missing video/workflows.
- HTTP 401 → set `COMPILE_API_KEY` to match the server.
- `status=failed` → show `error` from the job payload. Do not retry in a loop unless the user asks.
