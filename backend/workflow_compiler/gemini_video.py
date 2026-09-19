from __future__ import annotations

import json
import mimetypes
import sys
import time
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from workflow_compiler.env import gemini_api_key, gemini_model
from workflow_compiler.ir import WorkflowExtraction
from workflow_compiler.schema_util import json_schema_for_gemini as inline_json_schema

EXTRACT_PROMPT = """You are extracting reusable software workflows from a screen recording.

The recording shows a person using an application (often OpenEMR or similar clinical software).
Your job is NOT to narrate the video. Your job is to identify each distinct JOB the person
completed, and describe that job as structured workflow JSON.

A workflow is one coherent goal an agent could later perform as a single tool, for example:
- search a patient and schedule an appointment
- register a new patient and open an encounter
- document a visit with SOAP notes, vitals, and a prescription

Rules:
- Split into multiple workflows when the user clearly starts a different goal.
- Merge tiny UI clicks that serve one goal into one workflow with several steps.
- steps.action must be snake_case verbs (search_patient, create_appointment, create_encounter, record_vitals).
- inputs_observed must be snake_case names an API tool could take (patient_name, appointment_date, drug_name).
- Mark side_effect=true on steps that send email, prescribe, take payment, delete data, or otherwise have irreversible effects.
- Use notes for timestamps (mm:ss) and important UI labels.
- Ignore idle mouse movement, login chrome, and unrelated browsing unless it is the outcome of the workflow.
- If the same job is demonstrated twice with different example data, emit ONE workflow and put the varying values in inputs_observed.
- Return only the structured object. Do not include markdown.
"""


def json_schema_for_gemini() -> dict[str, Any]:
    return inline_json_schema(WorkflowExtraction)


def _generation_config(timeout_ms: int) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        temperature=0.2,
        response_mime_type="application/json",
        response_json_schema=json_schema_for_gemini(),
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        http_options=types.HttpOptions(timeout=timeout_ms),
    )


def extract_workflows_from_video(
    video: str | Path,
    *,
    api_key: str | None = None,
    model: str | None = None,
    timeout_sec: int = 600,
    extra_context: str | None = None,
) -> WorkflowExtraction:
    """Send a local video or YouTube URL to Gemini and return validated workflows."""
    key = api_key or gemini_api_key()
    model_name = model or gemini_model()
    timeout_ms = timeout_sec * 1000
    client = genai.Client(
        api_key=key,
        http_options=types.HttpOptions(timeout=timeout_ms),
    )

    video_str = str(video)
    prompt = EXTRACT_PROMPT
    extra = (extra_context or "").strip()
    if extra:
        prompt = (
            f"{EXTRACT_PROMPT}\n\nAdditional documentation from the user:\n{extra}\n"
        )
    uploaded_name: str | None = None
    try:
        video_part, uploaded_name = _prepare_video(
            client, video_str, timeout_sec=timeout_sec
        )
        print(
            "Asking Gemini to extract workflows "
            f"(often 1–3 minutes, model={model_name})...",
            file=sys.stderr,
            flush=True,
        )
        response = client.models.generate_content(
            model=model_name,
            contents=[video_part, prompt],
            config=_generation_config(timeout_ms),
        )
    finally:
        if uploaded_name:
            try:
                client.files.delete(name=uploaded_name)
            except Exception:
                pass

    extraction = _parse_response(response)
    if not extraction.workflows:
        raise RuntimeError("Gemini returned zero workflows for this video.")
    return extraction


def _prepare_video(client: genai.Client, video: str, timeout_sec: int = 600):
    if video.startswith("http://") or video.startswith("https://"):
        return types.Part.from_uri(file_uri=video, mime_type="video/mp4"), None

    path = Path(video).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)

    mime, _ = mimetypes.guess_type(path.name)
    if not mime:
        mime = "video/mp4"
    print(
        f"Uploading {path.name} to Gemini Files API ({mime})...",
        file=sys.stderr,
        flush=True,
    )
    uploaded = client.files.upload(file=str(path), config={"mime_type": mime})
    uploaded = _wait_until_active(client, uploaded, timeout_sec=timeout_sec)
    return uploaded, uploaded.name


def _wait_until_active(client: genai.Client, uploaded, timeout_sec: int = 600):
    deadline = time.time() + timeout_sec
    while True:
        state = str(getattr(uploaded.state, "name", uploaded.state)).split(".")[-1].upper()
        if state == "ACTIVE":
            print("Video is ready.", file=sys.stderr, flush=True)
            return uploaded
        if state == "FAILED":
            raise RuntimeError(f"Gemini failed to process the video: {uploaded}")
        if time.time() > deadline:
            raise TimeoutError("Timed out waiting for Gemini to process the video.")
        print(f"Processing video ({state})...", file=sys.stderr, flush=True)
        time.sleep(4)
        uploaded = client.files.get(name=uploaded.name)


def _parse_response(response) -> WorkflowExtraction:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, WorkflowExtraction):
        return parsed
    if isinstance(parsed, dict):
        return WorkflowExtraction.model_validate(parsed)
    if parsed is not None and hasattr(parsed, "workflows"):
        return WorkflowExtraction.model_validate(parsed)

    text = (getattr(response, "text", None) or "").strip()
    if not text:
        raise RuntimeError("Gemini returned an empty response.")
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    data = json.loads(text)
    if isinstance(data, list):
        data = {"workflows": data}
    return WorkflowExtraction.model_validate(data)


def extraction_to_dict(
    extraction: WorkflowExtraction,
    *,
    video: str,
    model: str,
) -> dict[str, Any]:
    return {
        "video": video,
        "model": model,
        "source": "gemini",
        "workflows": [item.model_dump() for item in extraction.workflows],
    }
