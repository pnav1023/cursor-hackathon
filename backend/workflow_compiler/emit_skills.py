from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from workflow_compiler.ir import ApiBinding, ApiMappingResult, UnmappedStep, WorkflowPlan
from workflow_compiler.openapi import Operation, operation_index

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def skill_slug(workflow_name: str, used: set[str] | None = None) -> str:
    slug = _SLUG_RE.sub("-", workflow_name.lower()).strip("-")[:64].strip("-")
    if not slug:
        slug = "workflow"
    if used is None:
        return slug
    base = slug
    n = 2
    while slug in used:
        suffix = f"-{n}"
        slug = (base[: 64 - len(suffix)] + suffix).strip("-")
        n += 1
    used.add(slug)
    return slug


def load_plans(path: str | Path) -> ApiMappingResult:
    payload = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    mapping = ApiMappingResult.model_validate(payload)
    if not mapping.workflows:
        raise RuntimeError("Plans file contains zero workflows.")
    return mapping


def render_skill(
    plan: WorkflowPlan,
    *,
    spec: dict[str, Any] | None = None,
    spec_title: str = "",
    spec_version: str = "",
    name: str | None = None,
) -> str:
    slug = name or skill_slug(plan.workflow_name)
    ops = operation_index(spec, include_fhir=True) if spec else {}
    title = spec_title or "the OpenAPI spec"
    version = f" {spec_version}" if spec_version else ""
    description = _description(plan, title, version)
    lines = [
        "---",
        f"name: {slug}",
        f"description: {json.dumps(description)}",
        "---",
        "",
        f"# {plan.workflow_name}",
        "",
        plan.goal.strip(),
        "",
        f"Grounded against **{title}{version}**. Call only the operations below.",
        "Copy method and path exactly. Do not invent endpoints or HTTP methods.",
        "",
        "## Inputs",
        "",
    ]
    if plan.inputs_observed:
        for item in plan.inputs_observed:
            lines.append(f"- `{item}`")
    else:
        lines.append("- None recorded from the source workflow.")
    lines.extend(["", "## API sequence", ""])
    if plan.apis:
        lines.append("Run these calls in order. Resolve path parameters from earlier responses.")
        lines.append("")
        for index, call in enumerate(plan.apis, start=1):
            lines.extend(_render_call(index, call, ops.get((call.method.upper(), call.path))))
    else:
        lines.append(
            "No operations in the spec cover this workflow. Do not invent fee-sheet, "
            "payment, receipt, or other missing paths."
        )
        lines.append("")
    if plan.unmapped:
        lines.extend(["## Out of spec", "", "Do not call an API for these observed UI steps:", ""])
        for skipped in plan.unmapped:
            lines.extend(_render_unmapped(skipped))
    lines.extend(
        [
            "## Auth",
            "",
            "OpenEMR standard REST uses OAuth2 (`openemr_auth`).",
            "Server base path is `/apis/default/` unless the spec says otherwise.",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def emit_skills(
    mapping: ApiMappingResult,
    out_dir: str | Path,
    *,
    spec: dict[str, Any] | None = None,
) -> list[Path]:
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    used: set[str] = set()
    for plan in mapping.workflows:
        slug = skill_slug(plan.workflow_name, used)
        dest = root / slug / "SKILL.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            render_skill(
                plan,
                spec=spec,
                spec_title=mapping.spec_title,
                spec_version=mapping.spec_version,
                name=slug,
            ),
            encoding="utf-8",
        )
        written.append(dest)
    return written


def skills_payload(
    mapping: ApiMappingResult,
    *,
    spec: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    used: set[str] = set()
    payload: list[dict[str, str]] = []
    for plan in mapping.workflows:
        slug = skill_slug(plan.workflow_name, used)
        payload.append(
            {
                "name": slug,
                "markdown": render_skill(
                    plan,
                    spec=spec,
                    spec_title=mapping.spec_title,
                    spec_version=mapping.spec_version,
                    name=slug,
                ),
            }
        )
    return payload


def _description(plan: WorkflowPlan, spec_title: str, version: str) -> str:
    if plan.apis:
        calls = ", ".join(f"{item.method} {item.path}" for item in plan.apis)
        what = f"Runs the OpenEMR workflow {plan.workflow_name} via {calls}."
    else:
        what = (
            f"Documents the OpenEMR workflow {plan.workflow_name}, which has no "
            "matching operations in the spec."
        )
    when = (
        f" Use when the user asks to {plan.goal[0].lower() + plan.goal[1:]}"
        if plan.goal
        else " Use when performing this OpenEMR workflow."
    )
    if not when.endswith("."):
        when += "."
    unmapped = ""
    if plan.unmapped:
        names = ", ".join(item.action for item in plan.unmapped)
        unmapped = f" Leaves {names} unmapped because those endpoints are not in {spec_title}{version}."
    text = what + when + unmapped
    return text[:1024]


def _render_call(index: int, call: ApiBinding, operation: Operation | None) -> list[str]:
    lines = [
        f"### {index}. `{call.method}` `{call.path}`",
        "",
        call.purpose.strip() or "Required step in this workflow.",
        "",
    ]
    if call.maps_from:
        lines.append("Covers: " + ", ".join(f"`{item}`" for item in call.maps_from))
        lines.append("")
    if call.params:
        lines.append("Field mapping (OpenAPI <- input):")
        lines.append("")
        for field, source in call.params.items():
            lines.append(f"- `{field}` <- `{source}`")
        lines.append("")
    if operation and operation.required:
        extras = [name for name in operation.required if name not in call.params]
        if extras:
            lines.append(
                "Required by the spec and not in the mapping: "
                + ", ".join(f"`{name}`" for name in extras)
            )
            lines.append("")
        if operation.description:
            lines.append(f"Spec: {operation.description}")
            lines.append("")
    elif operation and operation.description:
        lines.append(f"Spec: {operation.description}")
        lines.append("")
    return lines


def _render_unmapped(skipped: UnmappedStep) -> list[str]:
    return [f"- `{skipped.action}`: {skipped.reason.strip()}", ""]
