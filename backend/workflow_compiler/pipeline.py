from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from workflow_compiler.emit_skills import emit_skills, skills_payload
from workflow_compiler.gemini_video import extract_workflows_from_video, extraction_to_dict
from workflow_compiler.ir import (
    ApiMappingResult,
    UnmappedStep,
    Workflow,
    WorkflowExtraction,
    WorkflowPlan,
)
from workflow_compiler.map_apis import load_workflows, map_workflows_to_apis, mapping_to_dict
from workflow_compiler.openapi import load_openapi


class CompileInputError(ValueError):
    """Raised when a job is missing required inputs."""


def read_text_docs(paths: list[Path], *, max_chars: int = 80_000) -> str:
    chunks: list[str] = []
    used = 0
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        label = f"--- {path.name} ---\n{text.strip()}\n"
        if used + len(label) > max_chars:
            remain = max_chars - used
            if remain > 80:
                chunks.append(label[:remain] + "\n")
            break
        chunks.append(label)
        used += len(label)
    return "\n".join(chunks).strip()


def plans_without_spec(workflows: list[Workflow]) -> ApiMappingResult:
    plans: list[WorkflowPlan] = []
    for item in workflows:
        unmapped = [
            UnmappedStep(
                action=step.action,
                reason="No OpenAPI spec was provided, so this step cannot be grounded.",
            )
            for step in item.steps
        ]
        plans.append(
            WorkflowPlan(
                workflow_name=item.workflow_name,
                goal=item.goal,
                inputs_observed=item.inputs_observed,
                apis=[],
                unmapped=unmapped,
            )
        )
    return ApiMappingResult(
        spec_title="none",
        spec_version="",
        spec_path="",
        workflows=plans,
    )


def run_compile(
    *,
    video: str | Path | None = None,
    spec: str | Path | None = None,
    workflows: str | Path | list[Workflow] | None = None,
    extra_context: str | None = None,
    include_fhir: bool = False,
    out_dir: str | Path | None = None,
    extract_fn=extract_workflows_from_video,
    map_fn=map_workflows_to_apis,
) -> dict[str, Any]:
    """Run extract → map → emit. Skip extract if workflows are supplied; skip map if no spec."""
    dest = Path(out_dir) if out_dir else None
    if dest:
        dest.mkdir(parents=True, exist_ok=True)

    items = _load_or_extract(
        video=video,
        workflows=workflows,
        extra_context=extra_context,
        dest=dest,
        extract_fn=extract_fn,
    )

    spec_path = Path(spec).expanduser().resolve() if spec else None
    openapi: dict[str, Any] | None = None
    if spec_path:
        openapi = load_openapi(spec_path)
        mapping = map_fn(
            items,
            spec_path,
            include_fhir=include_fhir,
            extra_context=extra_context,
        )
    else:
        mapping = plans_without_spec(items)

    if dest:
        (dest / "plans.json").write_text(
            json.dumps(mapping_to_dict(mapping), indent=2) + "\n",
            encoding="utf-8",
        )
        emit_skills(mapping, dest / "skills", spec=openapi)

    skills = skills_payload(mapping, spec=openapi)
    return {
        "workflows": [item.model_dump() for item in items],
        "plans": mapping_to_dict(mapping),
        "skills": skills,
    }


def _load_or_extract(
    *,
    video: str | Path | None,
    workflows: str | Path | list[Workflow] | None,
    extra_context: str | None,
    dest: Path | None,
    extract_fn,
) -> list[Workflow]:
    if isinstance(workflows, list):
        items = workflows
    elif workflows:
        items = load_workflows(workflows)
    elif video:
        video_str = str(video)
        extraction: WorkflowExtraction = extract_fn(
            video_str, extra_context=extra_context
        )
        items = extraction.workflows
        if dest:
            payload = extraction_to_dict(
                extraction, video=video_str, model=""
            )
            (dest / "workflows.json").write_text(
                json.dumps(payload, indent=2) + "\n",
                encoding="utf-8",
            )
    else:
        raise CompileInputError(
            "Provide a video (file or URL) or a workflows JSON file."
        )
    if not items:
        raise CompileInputError("No workflows to compile.")
    if dest and not (dest / "workflows.json").is_file():
        payload = {"workflows": [item.model_dump() for item in items]}
        (dest / "workflows.json").write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )
    return items
