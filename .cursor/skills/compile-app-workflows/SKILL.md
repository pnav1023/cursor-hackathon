---
name: compile-app-workflows
description: Compiles a product recording and OpenAPI spec from the current chat into Cursor skills by POSTing them to the workflow-compiler FastAPI service. Use when the user asks to compile workflows, generate skills from a video or OpenAPI spec, or run the intake compile job.
---

# Compile App Workflows

Turn a screen recording plus an API spec into one Cursor skill per workflow. Inputs come from **this chat**, not from hardcoded demo files.

Do **not** extract workflows or invent REST paths yourself. The FastAPI service does that.

## Service

Default: `https://cursor-hackathon-6lgm.onrender.com`

Override with `COMPILE_API_URL` (local: `http://127.0.0.1:8000`). If `COMPILE_API_KEY` is set, send `Authorization: Bearer <key>`.

Pass the base URL into the client with `--base-url`.

## Inputs from chat

Resolve files from the current conversation, in this order:

1. Files the user attached or dragged into the chat
2. Files they `@`-mentioned
3. Paths they typed (absolute or repo-relative)

Write chat attachments to a real path on disk first if needed (mp4 and OpenAPI are uploaded as multipart files). Then pass those paths to the client.

| Input | Form field | Required? |
| --- | --- | --- |
| Screen recording `.mp4` | `video` | Yes, unless they gave `video_url` or workflows JSON |
| OpenAPI YAML/JSON | `spec` | Yes to ground skills; warn and continue only if they explicitly skip it |
| Extra notes / docs | `docs` | Optional |
| Pre-extracted workflows | `workflows` | Alternative to video |
| Remote video URL | `video_url` | Alternative to uploading `video` |

If video (or workflows) is missing, **ask for it**. Do not use `assets/openemr.mp4` or `fixtures/openemr/*` unless the user says to use the demo files.

## Run the job

From the repo root:

```bash
python .cursor/skills/compile-app-workflows/scripts/compile_job.py \
  --base-url https://cursor-hackathon-6lgm.onrender.com \
  --video PATH_FROM_CHAT \
  --spec PATH_FROM_CHAT \
  --out .cursor/skills
```

Add `--doc PATH_FROM_CHAT` for each extra doc. If they provided workflows JSON instead of a video, use `--workflows` and omit `--video`.

Do not call Gemini or OpenAI from this skill. Do not invent API paths.

Video jobs often take several minutes. Keep polling until the script exits.

## After success

1. Summarize `skill_count` and each written `.cursor/skills/<name>/SKILL.md`.
2. Call out skills whose body says they have **no matching operations**.
3. Do not rewrite the generated markdown to add APIs.

## Failures

- Health check failed → the Render service may be sleeping; retry `/health` once, then report the error.
- HTTP 400 "Provide a video file..." → the chat did not yield a video/workflows file.
- HTTP 401 → set `COMPILE_API_KEY` to match Render.
- `status=failed` → show `error`. Do not retry in a loop unless the user asks.
