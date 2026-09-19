#!/usr/bin/env python3
"""POST a compile job to the FastAPI service and write returned SKILL.md files."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("COMPILE_API_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--video", type=Path)
    parser.add_argument("--video-url")
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--workflows", type=Path)
    parser.add_argument("--doc", type=Path, action="append", default=[], dest="docs")
    parser.add_argument("--include-fhir", action="store_true")
    parser.add_argument("--out", type=Path, default=Path(".cursor/skills"))
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--poll", type=float, default=3.0)
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    api_key = os.environ.get("COMPILE_API_KEY", "").strip()
    has_video = bool(args.video) or bool((args.video_url or "").strip())
    if not has_video and not args.workflows:
        print("Provide --video, --video-url, or --workflows.", file=sys.stderr)
        return 2

    try:
        health = _request("GET", f"{base}/health", api_key=api_key)
    except Exception as exc:
        print(f"Cannot reach {base}/health: {exc}", file=sys.stderr)
        print("Start the service: PYTHONPATH=backend uvicorn workflow_compiler.service:app --reload --port 8000", file=sys.stderr)
        return 1
    if health.get("status") != "ok":
        print(f"Service unhealthy: {health}", file=sys.stderr)
        return 1

    fields: list[tuple[str, str]] = [("include_fhir", "true" if args.include_fhir else "false")]
    if args.video_url:
        fields.append(("video_url", args.video_url.strip()))
    files: list[tuple[str, Path]] = []
    if args.video:
        files.append(("video", args.video))
    if args.spec:
        files.append(("spec", args.spec))
    if args.workflows:
        files.append(("workflows", args.workflows))
    for doc in args.docs:
        files.append(("docs", doc))

    print(f"POST {base}/v1/jobs", flush=True)
    try:
        created = _request("POST", f"{base}/v1/jobs", api_key=api_key, fields=fields, files=files)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"Create job failed ({exc.code}): {body}", file=sys.stderr)
        return 1

    job_id = created["id"]
    print(f"job {job_id} status={created.get('status')} stage={created.get('stage')}", flush=True)
    deadline = time.time() + args.timeout
    job = created
    while job.get("status") in {"queued", "running"}:
        if time.time() > deadline:
            print(f"Timed out waiting for job {job_id}", file=sys.stderr)
            return 1
        time.sleep(args.poll)
        job = _request("GET", f"{base}/v1/jobs/{job_id}", api_key=api_key)
        print(f"job {job_id} status={job.get('status')} stage={job.get('stage')}", flush=True)

    if job.get("status") != "done":
        print(f"Job failed: {job.get('error') or job}", file=sys.stderr)
        return 1

    result = _request("GET", f"{base}/v1/jobs/{job_id}/result", api_key=api_key)
    out_dir = args.out.expanduser().resolve()
    written: list[str] = []
    for skill in result.get("skills") or []:
        name = skill.get("name")
        markdown = skill.get("markdown")
        if not name or not markdown:
            continue
        dest = out_dir / name / "SKILL.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(markdown, encoding="utf-8")
        written.append(str(dest))
        print(f"wrote {dest}", flush=True)

    print(json.dumps({"id": job_id, "skill_count": len(written), "skills": written}, indent=2))
    return 0


def _request(
    method: str,
    url: str,
    *,
    api_key: str = "",
    fields: list[tuple[str, str]] | None = None,
    files: list[tuple[str, Path]] | None = None,
) -> dict:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    data = None
    if fields or files:
        data, content_type = _multipart(fields or [], files or [])
        headers["Content-Type"] = content_type
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=60) as response:
            payload = response.read().decode("utf-8")
    except HTTPError as exc:
        if method == "GET" and exc.code == 409:
            payload = exc.read().decode("utf-8")
            return json.loads(payload) if payload else {"status": "running"}
        raise
    except URLError:
        raise
    return json.loads(payload) if payload else {}


def _multipart(fields: list[tuple[str, str]], files: list[tuple[str, Path]]) -> tuple[bytes, str]:
    boundary = f"----compile{uuid.uuid4().hex}"
    lines: list[bytes] = []
    for name, value in fields:
        lines.append(f"--{boundary}".encode())
        lines.append(f'Content-Disposition: form-data; name="{name}"'.encode())
        lines.append(b"")
        lines.append(value.encode())
    for name, path in files:
        path = path.expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        lines.append(f"--{boundary}".encode())
        lines.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{path.name}"'.encode()
        )
        lines.append(f"Content-Type: {mime}".encode())
        lines.append(b"")
        lines.append(path.read_bytes())
    lines.append(f"--{boundary}--".encode())
    lines.append(b"")
    return b"\r\n".join(lines), f"multipart/form-data; boundary={boundary}"


if __name__ == "__main__":
    raise SystemExit(main())
