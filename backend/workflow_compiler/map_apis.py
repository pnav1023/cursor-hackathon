from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from openai import APIError, APITimeoutError, AuthenticationError, OpenAI

from workflow_compiler.env import openai_api_key, openai_model
from workflow_compiler.ir import (
    ApiBinding,
    ApiMappingResult,
    UnmappedStep,
    Workflow,
    WorkflowExtraction,
    WorkflowPlan,
)
from workflow_compiler.openapi import (
    UngroundedApiError,
    canonicalize_call,
    catalog_text,
    list_operations,
    load_openapi,
)

MAP_PROMPT = """You map structured UI workflows onto a real OpenAPI spec.

You may ONLY use operations from the catalog below. Copy method and path EXACTLY
as listed, including HTTP method. If the catalog has GET and POST but not PUT,
you must not emit PUT.

If a human step has no matching operation (UI layout, fee sheet, checkout, receipts,
appointment check-in / status change, login chrome), put it in unmapped with a reason.
NEVER invent paths such as /api/fee-sheet, /api/payment, /api/receipt, /api/inventory-alerts.
NEVER invent methods on a real path (there is no PUT or PATCH for OpenEMR appointments).
OpenEMR appointment operations in the standard API are only:
  GET /api/appointment
  GET /api/appointment/{eid}
  GET /api/patient/{pid}/appointment
  POST /api/patient/{pid}/appointment
  GET /api/patient/{pid}/appointment/{eid}
  DELETE /api/patient/{pid}/appointment/{eid}
Check-in is unmapped. OpenEMR POST /api/patient/{pid}/transaction is a referral record,
not a payment, fee sheet, or receipt — do not use it for billing/checkout.

Prefer the standard /api/... REST operations an agent would call, not FHIR, unless the
workflow is explicitly about FHIR interoperability.

Several API calls can belong to one workflow. One workflow is later one agent tool.
Skip idle navigation. Preserve inputs_observed.

Return a JSON object matching the schema. No markdown.
"""


def load_workflows(path: str | Path) -> list[Workflow]:
    payload = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    if isinstance(payload, list):
        payload = {"workflows": payload}
    extraction = WorkflowExtraction.model_validate(payload)
    if not extraction.workflows:
        raise RuntimeError("Workflows file contains zero workflows.")
    return extraction.workflows


def map_workflows_to_apis(
    workflows: str | Path | list[Workflow],
    spec: str | Path,
    *,
    api_key: str | None = None,
    model: str | None = None,
    include_fhir: bool = False,
    timeout_sec: int = 180,
    extra_context: str | None = None,
) -> ApiMappingResult:
    spec_path = Path(spec).expanduser().resolve()
    openapi = load_openapi(spec_path)
    operations = list_operations(openapi, include_fhir=include_fhir)
    if not operations:
        raise RuntimeError(f"No operations found in {spec_path}.")

    items = workflows if isinstance(workflows, list) else load_workflows(workflows)
    info = openapi.get("info") or {}
    draft = _ask_openai(
        items,
        operations,
        api_key=api_key,
        model=model,
        timeout_sec=timeout_sec,
        spec_title=str(info.get("title") or spec_path.name),
        spec_version=str(info.get("version") or ""),
        spec_path=str(spec_path),
        extra_context=extra_context,
    )
    return validate_mapping(
        draft, openapi, spec_path=spec_path, drop_ungrounded=True
    )


def validate_mapping(
    mapping: ApiMappingResult,
    spec: dict[str, Any],
    *,
    spec_path: Path | None = None,
    drop_ungrounded: bool = False,
) -> ApiMappingResult:
    grounded: list[WorkflowPlan] = []
    errors: list[str] = []
    for plan in mapping.workflows:
        apis: list[ApiBinding] = []
        unmapped = list(plan.unmapped)
        for call in plan.apis:
            try:
                method, path = canonicalize_call(call.method, call.path, spec=spec)
            except UngroundedApiError as exc:
                message = f"{plan.workflow_name}: {exc}"
                if drop_ungrounded:
                    action = call.maps_from[0] if call.maps_from else call.purpose
                    unmapped.append(
                        UnmappedStep(
                            action=action or f"{call.method} {call.path}",
                            reason=str(exc),
                        )
                    )
                    print(f"Dropped invented call: {message}", file=sys.stderr)
                    continue
                errors.append(message)
                continue
            apis.append(call.model_copy(update={"method": method, "path": path}))
        grounded.append(plan.model_copy(update={"apis": apis, "unmapped": unmapped}))
    if errors:
        raise UngroundedApiError("\n".join(errors))
    info = spec.get("info") or {}
    return mapping.model_copy(
        update={
            "spec_title": str(info.get("title") or mapping.spec_title),
            "spec_version": str(info.get("version") or mapping.spec_version),
            "spec_path": str(spec_path) if spec_path else mapping.spec_path,
            "workflows": grounded,
        }
    )


def mapping_to_dict(mapping: ApiMappingResult) -> dict[str, Any]:
    return mapping.model_dump()


def _ask_openai(
    workflows: list[Workflow],
    operations,
    *,
    api_key: str | None,
    model: str | None,
    timeout_sec: int,
    spec_title: str,
    spec_version: str,
    spec_path: str,
    extra_context: str | None = None,
) -> ApiMappingResult:
    key = api_key or openai_api_key()
    model_name = model or openai_model()
    catalog = catalog_text(operations)
    payload = {
        "spec_title": spec_title,
        "spec_version": spec_version,
        "workflows": [item.model_dump() for item in workflows],
    }
    user_prompt = (
        f"OpenAPI catalog ({len(operations)} operations):\n{catalog}\n\n"
        f"Workflows JSON:\n{json.dumps(payload, indent=2)}\n"
    )
    extra = (extra_context or "").strip()
    if extra:
        user_prompt += f"\nAdditional documentation from the user:\n{extra}\n"
    system_prompt = (
        f"{MAP_PROMPT}\n\nJSON schema:\n"
        f"{json.dumps(ApiMappingResult.model_json_schema(), indent=2)}"
    )
    print(
        f"Mapping {len(workflows)} workflow(s) onto {len(operations)} spec operations "
        f"with {model_name}...",
        file=sys.stderr,
        flush=True,
    )
    client = OpenAI(api_key=key, timeout=timeout_sec)
    try:
        completion = client.chat.completions.create(
            model=model_name,
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
    except AuthenticationError as exc:
        raise RuntimeError(
            "OpenAI authentication failed. Set OPENAI_API_KEY in .env."
        ) from exc
    except APITimeoutError as exc:
        raise TimeoutError(f"OpenAI mapping timed out after {timeout_sec}s.") from exc
    except APIError as exc:
        raise RuntimeError(f"OpenAI mapping failed: {exc}") from exc

    message = completion.choices[0].message
    refusal = getattr(message, "refusal", None)
    if refusal:
        raise RuntimeError(f"OpenAI refused the mapping request: {refusal}")
    parsed = _parse_mapping_text(message.content or "")
    return parsed.model_copy(
        update={
            "spec_title": spec_title,
            "spec_version": spec_version,
            "spec_path": spec_path,
        }
    )


def _parse_mapping_text(text: str) -> ApiMappingResult:
    text = (text or "").strip()
    if not text:
        raise RuntimeError("OpenAI returned an empty API mapping.")
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return ApiMappingResult.model_validate(json.loads(text))
