from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from workflow_compiler.env import load_env_files
from workflow_compiler.jobs import JobStore

MAX_VIDEO_BYTES = 100 * 1024 * 1024
MAX_SPEC_BYTES = 8 * 1024 * 1024
MAX_WORKFLOWS_BYTES = 2 * 1024 * 1024
MAX_DOC_BYTES = 2 * 1024 * 1024
MAX_DOCS = 8
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")

load_env_files()
app = FastAPI(
    title="Workflow compiler",
    version="0.1.0",
    description="Upload a video and/or OpenAPI spec; poll for generated Cursor skills.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
store = JobStore()


def _api_key(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    load_env_files()
    expected = os.environ.get("COMPILE_API_KEY", "").strip()
    if not expected:
        return
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if token != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/jobs", status_code=202, dependencies=[Depends(_api_key)])
async def create_job(
    background: BackgroundTasks,
    video: UploadFile | None = File(default=None),
    spec: UploadFile | None = File(default=None),
    workflows: UploadFile | None = File(default=None),
    docs: list[UploadFile] | None = File(default=None),
    video_url: str | None = Form(default=None),
    include_fhir: bool = Form(default=False),
):
    video_url = (video_url or "").strip() or None
    doc_files = [item for item in (docs or []) if item and item.filename]
    has_video = _has_file(video) or bool(video_url)
    has_workflows = _has_file(workflows)
    if not has_video and not has_workflows:
        raise HTTPException(
            status_code=400,
            detail="Provide a video file, video_url, or workflows JSON.",
        )
    if len(doc_files) > MAX_DOCS:
        raise HTTPException(status_code=400, detail=f"At most {MAX_DOCS} extra docs.")

    meta = store.create()
    job_id = meta["id"]
    inputs_dir = store.dir(job_id) / "inputs"
    saved = {
        "video": None,
        "video_url": video_url,
        "spec": None,
        "workflows": None,
        "docs": [],
    }
    try:
        if _has_file(video):
            saved["video"] = str(
                await _save_upload(
                    video, inputs_dir / _safe_name(video.filename, "video.mp4"), MAX_VIDEO_BYTES
                )
            )
        if _has_file(spec):
            saved["spec"] = str(
                await _save_upload(
                    spec, inputs_dir / _safe_name(spec.filename, "openapi.yaml"), MAX_SPEC_BYTES
                )
            )
        if _has_file(workflows):
            saved["workflows"] = str(
                await _save_upload(
                    workflows,
                    inputs_dir / _safe_name(workflows.filename, "workflows.json"),
                    MAX_WORKFLOWS_BYTES,
                )
            )
        for index, doc in enumerate(doc_files):
            dest = inputs_dir / "docs" / f"{index:02d}-{_safe_name(doc.filename, 'doc.txt')}"
            saved["docs"].append(str(await _save_upload(doc, dest, MAX_DOC_BYTES)))
    except ValueError as exc:
        store.patch(job_id, status="failed", stage="failed", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    store.patch(job_id, inputs=saved)
    background.add_task(store.run, job_id, include_fhir=include_fhir)
    current = store.get(job_id) or meta
    return JSONResponse(status_code=202, content=_public(current))


@app.get("/v1/jobs/{job_id}", dependencies=[Depends(_api_key)])
def get_job(job_id: str, include_markdown: bool = False) -> dict:
    meta = store.get(job_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return _public(meta, include_markdown=include_markdown)


@app.get("/v1/jobs/{job_id}/result", dependencies=[Depends(_api_key)])
def get_result(job_id: str) -> dict:
    meta = store.get(job_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if meta.get("status") != "done":
        raise HTTPException(
            status_code=409,
            detail=f"Job is {meta.get('status')}. Poll GET /v1/jobs/{job_id} until status=done.",
        )
    return _public(meta, include_markdown=True)


def _public(meta: dict, *, include_markdown: bool = False) -> dict:
    skills = meta.get("skills") or []
    if not include_markdown:
        skills = [{"name": item.get("name")} for item in skills]
    return {
        "id": meta.get("id"),
        "status": meta.get("status"),
        "stage": meta.get("stage"),
        "error": meta.get("error"),
        "created_at": meta.get("created_at"),
        "updated_at": meta.get("updated_at"),
        "skill_count": meta.get("skill_count") or 0,
        "skills": skills,
    }


def _has_file(upload: UploadFile | None) -> bool:
    return upload is not None and bool(upload.filename)


def _safe_name(name: str | None, fallback: str) -> str:
    raw = Path(name or "").name or fallback
    cleaned = _SAFE_NAME.sub("-", raw).strip(".-")
    return cleaned or fallback


async def _save_upload(upload: UploadFile, dest: Path, max_bytes: int) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with dest.open("wb") as handle:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                handle.close()
                dest.unlink(missing_ok=True)
                raise ValueError(f"{upload.filename or dest.name} exceeds {max_bytes} bytes.")
            handle.write(chunk)
    await upload.close()
    if size == 0:
        dest.unlink(missing_ok=True)
        raise ValueError(f"{upload.filename or dest.name} is empty.")
    return dest.resolve()


def main() -> None:
    import uvicorn

    load_env_files()
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(
        "workflow_compiler.service:app",
        host="0.0.0.0",
        port=port,
        reload=os.environ.get("COMPILE_RELOAD", "").strip() == "1",
    )
