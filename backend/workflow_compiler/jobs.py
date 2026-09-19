from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from workflow_compiler.env import load_env_files
from workflow_compiler.pipeline import CompileInputError, read_text_docs, run_compile

_lock = threading.Lock()


def jobs_root() -> Path:
    import os

    load_env_files()
    override = os.environ.get("COMPILE_JOBS_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "dist" / "jobs"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class JobStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root else jobs_root()
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self) -> dict[str, Any]:
        job_id = uuid.uuid4().hex[:12]
        path = self.root / job_id
        (path / "inputs" / "docs").mkdir(parents=True, exist_ok=True)
        meta = {
            "id": job_id,
            "status": "queued",
            "stage": "queued",
            "error": None,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "inputs": {
                "video": None,
                "video_url": None,
                "spec": None,
                "workflows": None,
                "docs": [],
            },
            "skill_count": 0,
            "skills": [],
        }
        self._write(job_id, meta)
        return meta

    def get(self, job_id: str) -> dict[str, Any] | None:
        path = self._meta_path(job_id)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def dir(self, job_id: str) -> Path:
        return self.root / job_id

    def patch(self, job_id: str, **fields: Any) -> dict[str, Any]:
        with _lock:
            meta = self.get(job_id)
            if meta is None:
                raise KeyError(job_id)
            meta.update(fields)
            meta["updated_at"] = utc_now()
            self._write(job_id, meta)
            return meta

    def run(self, job_id: str, *, include_fhir: bool = False) -> dict[str, Any]:
        meta = self.get(job_id)
        if meta is None:
            raise KeyError(job_id)
        inputs = meta.get("inputs") or {}
        job_dir = self.dir(job_id)
        video = inputs.get("video") or inputs.get("video_url")
        spec = inputs.get("spec")
        workflows = inputs.get("workflows")
        docs = [Path(item) for item in (inputs.get("docs") or [])]
        extra = read_text_docs(docs)
        try:
            self.patch(job_id, status="running", stage="compiling", error=None)
            result = run_compile(
                video=video,
                spec=spec,
                workflows=workflows,
                extra_context=extra or None,
                include_fhir=include_fhir,
                out_dir=job_dir,
            )
            skills = result.get("skills") or []
            return self.patch(
                job_id,
                status="done",
                stage="done",
                error=None,
                skill_count=len(skills),
                skills=skills,
            )
        except CompileInputError as exc:
            return self.patch(job_id, status="failed", stage="failed", error=str(exc))
        except Exception as exc:
            return self.patch(job_id, status="failed", stage="failed", error=str(exc))

    def _meta_path(self, job_id: str) -> Path:
        return self.dir(job_id) / "meta.json"

    def _write(self, job_id: str, meta: dict[str, Any]) -> None:
        path = self._meta_path(job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
